"""
Darwinbox HRMS connector plugin for AVIS Connect.

Auth: API Key passed as a header or query param (Darwinbox v2 REST API).

Credential keys (stored encrypted in connect.credentials):
  api_key       — Darwinbox API key from Settings → Integrations
  base_url      — Tenant base URL, e.g. https://yourcompany.darwinbox.in
  company_id    — Darwinbox company/tenant ID

Endpoint convention (stored in connect.operations):
  endpoint = relative path, e.g. /api/employee/list
  Full URL built as: {base_url}{endpoint}

Operations for RMS:
  get_employees     GET   /api/employee/list        Pull full employee roster
  get_employee      GET   /api/employee/{id}        Fetch one employee by ID
  get_leavers       GET   /api/employee/list        Employees with status=exit
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from app.connectors.base import BaseConnector

log = logging.getLogger(__name__)


class DarwinboxConnector(BaseConnector):
    """Darwinbox HRMS REST API — API key authentication."""

    name = "darwinbox"

    def execute(
        self,
        operation: str,
        endpoint: str,
        method: str,
        payload: dict[str, Any],
        credentials: dict[str, str],
    ) -> dict:
        api_key    = credentials["api_key"]
        base_url   = credentials["base_url"].rstrip("/")
        company_id = credentials.get("company_id", "")

        url  = endpoint if endpoint.startswith("http") else f"{base_url}{endpoint}"
        verb = method.upper()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }
        if company_id:
            headers["X-Company-ID"] = company_id

        log.info("Darwinbox %s %s [op=%s]", verb, url, operation)

        if verb == "GET":
            resp = requests.get(url, params=payload or None, headers=headers, timeout=30)
        elif verb == "POST":
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
        elif verb == "PATCH":
            resp = requests.patch(url, json=payload, headers=headers, timeout=30)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(
                f"Darwinbox {resp.status_code} for op={operation}: {resp.text[:500]}"
            )

        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}

    def health_check(self, credentials: dict[str, str]) -> bool:
        """Ping the employee list endpoint with limit=1."""
        try:
            result = self.execute(
                "health_check", "/api/employee/list", "GET",
                {"limit": 1}, credentials,
            )
            return isinstance(result, dict)
        except Exception as exc:
            log.warning("Darwinbox health check failed: %s", exc)
            return False
