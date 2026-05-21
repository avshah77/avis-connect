"""
NetSuite SuiteTalk REST connector — OAuth 1.0a Token-Based Authentication (TBA).

Credential keys (stored encrypted in connect.credentials):
  account_id      — NS Account ID, e.g. 1234567 or 1234567_SB1 for sandbox
  consumer_key    — OAuth consumer key from the integration record
  consumer_secret — OAuth consumer secret
  token_id        — Access token ID
  token_secret    — Access token secret

Endpoint stored in connect.operations (relative path):
  /projectresource   → create_allocation
  /salesorder        → create_so
  /invoice           → create_invoice
  /journalentry      → create_journal
  /job               → get_project  (GET with ?q= query)

Full URL: https://{ACCOUNT_ID}.suitetalk.api.netsuite.com/services/rest/record/v1{endpoint}

Payload convention:
  POST/PATCH — caller sends NS-ready JSON body (no transformation here)
  GET        — payload dict becomes URL query params (e.g. {"q": 'externalId IS "X"'})
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from base64 import b64encode
from typing import Any
from urllib.parse import quote

import requests

from connect.connectors.base import BaseConnector

log = logging.getLogger(__name__)

_BASE_TEMPLATE = "https://{acct}.suitetalk.api.netsuite.com/services/rest/record/v1"


def _base_url(account_id: str) -> str:
    acct = account_id.upper().replace("-", "_")
    return _BASE_TEMPLATE.format(acct=acct)


def _tba_header(
    account_id: str,
    consumer_key: str,
    consumer_secret: str,
    token_id: str,
    token_secret: str,
    method: str,
    url: str,
    extra_params: dict[str, str] | None = None,
) -> str:
    """Build OAuth 1.0a Authorization header for NetSuite TBA."""
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex

    oauth_params: dict[str, str] = {
        "oauth_consumer_key":     consumer_key,
        "oauth_nonce":            nonce,
        "oauth_signature_method": "HMAC-SHA256",
        "oauth_timestamp":        timestamp,
        "oauth_token":            token_id,
        "oauth_version":          "1.0",
    }
    all_params = {**oauth_params, **(extra_params or {})}
    sorted_params = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}"
        for k, v in sorted(all_params.items())
    )

    base_string = "&".join([
        method.upper(),
        quote(url, safe=""),
        quote(sorted_params, safe=""),
    ])

    signing_key = f"{quote(consumer_secret, safe='')}&{quote(token_secret, safe='')}"
    signature = b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha256).digest()
    ).decode()

    header_parts = [
        f'realm="{account_id}"',
        f'oauth_consumer_key="{consumer_key}"',
        f'oauth_token="{token_id}"',
        'oauth_signature_method="HMAC-SHA256"',
        f'oauth_timestamp="{timestamp}"',
        f'oauth_nonce="{nonce}"',
        'oauth_version="1.0"',
        f'oauth_signature="{quote(signature, safe="")}"',
    ]
    return "OAuth " + ",".join(header_parts)


class NetSuiteConnector(BaseConnector):
    """NetSuite SuiteTalk REST — OAuth 1.0a TBA."""

    name = "netsuite"

    def execute(
        self,
        operation: str,
        endpoint: str,
        method: str,
        payload: dict[str, Any],
        credentials: dict[str, str],
    ) -> dict:
        account_id      = credentials["account_id"]
        consumer_key    = credentials["consumer_key"]
        consumer_secret = credentials["consumer_secret"]
        token_id        = credentials["token_id"]
        token_secret    = credentials["token_secret"]

        base = _base_url(account_id)
        url  = endpoint if endpoint.startswith("http") else f"{base}{endpoint}"
        verb = method.upper()

        # For GET, payload becomes query params — include them in the OAuth signature
        extra_params = {k: str(v) for k, v in payload.items()} if verb == "GET" else None

        auth = _tba_header(
            account_id, consumer_key, consumer_secret,
            token_id, token_secret,
            verb, url, extra_params=extra_params,
        )
        headers = {
            "Authorization": auth,
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

        log.info("NS %s %s [op=%s]", verb, url, operation)

        if verb == "GET":
            resp = requests.get(url, params=payload, headers=headers, timeout=30)
        elif verb == "POST":
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
        elif verb == "PATCH":
            resp = requests.patch(url, json=payload, headers=headers, timeout=30)
        elif verb == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=30)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(
                f"NetSuite {resp.status_code} for op={operation}: {resp.text[:500]}"
            )

        # 204 No Content — NS ID lives in Location header
        if resp.status_code == 204:
            location = resp.headers.get("Location", "")
            ns_id = location.rstrip("/").split("/")[-1] if location else None
            return {"ns_id": ns_id, "status": "success", "http_status": 204}

        try:
            data: dict = resp.json()
        except Exception:
            data = {"raw": resp.text}

        # Attach NS internal ID from Location header when present (201 Created)
        location = resp.headers.get("Location", "")
        if location and isinstance(data, dict):
            data.setdefault("ns_id", location.rstrip("/").split("/")[-1])

        return data

    def health_check(self, credentials: dict[str, str]) -> bool:
        """Hit the NS metadata catalog — 200/30x means the account is reachable."""
        try:
            account_id      = credentials["account_id"]
            consumer_key    = credentials["consumer_key"]
            consumer_secret = credentials["consumer_secret"]
            token_id        = credentials["token_id"]
            token_secret    = credentials["token_secret"]

            acct = account_id.upper().replace("-", "_")
            url  = f"https://{acct}.suitetalk.api.netsuite.com/services/rest/record/v1/metadata-catalog"
            auth = _tba_header(
                account_id, consumer_key, consumer_secret,
                token_id, token_secret, "GET", url,
            )
            resp = requests.get(
                url,
                headers={"Authorization": auth, "Accept": "application/json"},
                timeout=10,
            )
            return resp.status_code in (200, 301, 302)
        except Exception:
            return False
