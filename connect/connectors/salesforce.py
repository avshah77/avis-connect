"""
Salesforce connector plugin for AVIS Connect.

Auth: Username + Password + Security Token (handled by simple-salesforce).

Credential keys (stored encrypted in connect.credentials):
  username        — SF login email
  password        — SF password
  security_token  — SF API security token (from Setup → My Personal Information)
  domain          — "login" (production) or "test" (sandbox). Default: login
  api_version     — e.g. "59.0". Default: 59.0

Endpoint + method convention (stored in connect.operations):
  endpoint=query          method=GET     → SOQL SELECT
  endpoint=<SObjectName>  method=GET     → fetch one record by sf_id in payload
  endpoint=<SObjectName>  method=POST    → create new record
  endpoint=<SObjectName>  method=PATCH   → update record (payload must include "sf_id")
  endpoint=<SObjectName>  method=DELETE  → delete record (payload must include "sf_id")

Payload conventions:
  For GET query:    {"q": "SELECT Id, Name FROM Opportunity WHERE ..."}
  For GET record:   {"sf_id": "003xxxxxxxxxxxx"}
  For POST create:  {field: value, ...}  (no sf_id)
  For PATCH update: {"sf_id": "003xxxxxxxxxxxx", field: value, ...}
  For DELETE:       {"sf_id": "003xxxxxxxxxxxx"}

Common use cases for RMS:
  - Write back NS Sales Order number to Opportunity after SO push
  - Write back NS invoice ID to Opportunity after invoice push
  - Query pipeline for forecasting sync
"""
from __future__ import annotations

import logging
from typing import Any

from connect.connectors.base import BaseConnector

log = logging.getLogger(__name__)


class SalesforceConnector(BaseConnector):
    """Salesforce REST connector — username/password/security_token auth."""

    name = "salesforce"

    def _client(self, credentials: dict[str, str]):
        """Return an authenticated simple_salesforce.Salesforce client."""
        try:
            from simple_salesforce import Salesforce
        except ImportError:
            raise RuntimeError(
                "simple-salesforce package is not installed. "
                "Run: pip install simple-salesforce"
            )
        return Salesforce(
            username       = credentials["username"],
            password       = credentials["password"],
            security_token = credentials["security_token"],
            domain         = credentials.get("domain", "login"),
            version        = credentials.get("api_version", "59.0"),
        )

    def execute(
        self,
        operation: str,
        endpoint: str,
        method: str,
        payload: dict[str, Any],
        credentials: dict[str, str],
    ) -> dict:
        sf     = self._client(credentials)
        verb   = method.upper()
        ep     = endpoint.strip().rstrip("/")

        log.info("SF %s %s [op=%s]", verb, ep, operation)

        # ── SOQL query ────────────────────────────────────────────────────────
        if ep.lower() == "query" and verb == "GET":
            soql = payload.get("q") or payload.get("soql")
            if not soql:
                raise ValueError("Payload must include 'q' or 'soql' for a query operation")
            result = sf.query_all(soql)
            records = result.get("records", [])
            for r in records:
                r.pop("attributes", None)
                # Flatten nested objects one level (e.g. Account.Name)
                for k, v in list(r.items()):
                    if isinstance(v, dict) and "attributes" in v:
                        v.pop("attributes", None)
            return {"totalSize": result.get("totalSize", len(records)), "records": records}

        # ── SObject operations ────────────────────────────────────────────────
        sobject = getattr(sf, ep, None)
        if sobject is None:
            raise ValueError(f"SObject '{ep}' not found in this Salesforce org")

        if verb == "GET":
            sf_id = payload.get("sf_id")
            if not sf_id:
                raise ValueError("Payload must include 'sf_id' for a GET record operation")
            record = sobject.get(sf_id)
            if isinstance(record, dict):
                record.pop("attributes", None)
            return record or {}

        if verb == "POST":
            result = sobject.create(payload)
            # Returns {"id": "...", "success": True, "errors": []}
            return {"sf_id": result.get("id"), "success": result.get("success", False),
                    "errors": result.get("errors", [])}

        if verb == "PATCH":
            sf_id  = payload.pop("sf_id", None)
            if not sf_id:
                raise ValueError("Payload must include 'sf_id' for a PATCH operation")
            http_status = sobject.update(sf_id, payload)
            # simple-salesforce returns the HTTP status code (204 = success)
            return {"sf_id": sf_id, "http_status": http_status,
                    "success": http_status in (200, 204)}

        if verb == "DELETE":
            sf_id = payload.get("sf_id")
            if not sf_id:
                raise ValueError("Payload must include 'sf_id' for a DELETE operation")
            http_status = sobject.delete(sf_id)
            return {"sf_id": sf_id, "http_status": http_status,
                    "success": http_status in (200, 204)}

        raise ValueError(f"Unsupported method '{method}' for Salesforce connector")

    def health_check(self, credentials: dict[str, str]) -> bool:
        """Verify credentials by connecting and running a cheap query."""
        try:
            sf = self._client(credentials)
            sf.query("SELECT COUNT() FROM Organization")
            return True
        except Exception as exc:
            log.warning("SF health check failed: %s", exc)
            return False
