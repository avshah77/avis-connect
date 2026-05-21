"""
AVIS Connect — Admin JSON API (CRUD for projects, connectors, credentials, operations).
"""
from __future__ import annotations

import os
import re
import textwrap

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.db import get_db
from app.models import ConnectorConfig, Credential, Operation, Project

router = APIRouter(prefix="/admin", tags=["admin"])

# Default operations seeded automatically when a new connector is created.
_DEFAULT_OPS: dict[str, list[dict]] = {
    "salesforce": [
        {"operation_name": "get_10_opportunities", "endpoint": "query",  "method": "GET",   "description": "Sample 10 Opportunities — quick test query"},
        {"operation_name": "get_opportunities",    "endpoint": "query",  "method": "GET",   "description": "List open Opportunities via SOQL"},
        {"operation_name": "get_contacts",         "endpoint": "query",  "method": "GET",   "description": "List Contacts via SOQL"},
        {"operation_name": "get_leads",            "endpoint": "query",  "method": "GET",   "description": "List open (unconverted) Leads via SOQL"},
        {"operation_name": "so_writeback",         "endpoint": "Opportunity", "method": "PATCH", "description": "Write NS Sales Order number back to Opportunity"},
        {"operation_name": "invoice_writeback",    "endpoint": "Opportunity", "method": "PATCH", "description": "Write NS Invoice ID back to Opportunity"},
    ],
    "netsuite": [
        {"operation_name": "create_allocation", "endpoint": "/projectresource", "method": "POST", "description": "Push resource allocation after BU Head approval"},
        {"operation_name": "create_so",         "endpoint": "/salesorder",      "method": "POST", "description": "Create Sales Order after RevOps + BFM approval"},
        {"operation_name": "create_invoice",    "endpoint": "/invoice",         "method": "POST", "description": "Generate invoice after timesheet compliance confirmed"},
        {"operation_name": "create_journal",    "endpoint": "/journalentry",    "method": "POST", "description": "Post GL journal entry after invoice approved"},
        {"operation_name": "get_project",       "endpoint": "/job",             "method": "GET",  "description": "Fetch NS Job record by externalId"},
    ],
}


# ── Pydantic models ───────────────────────────────────────────────────────────

class ProjectIn(BaseModel):
    slug:        str
    name:        str
    description: str | None = None
    active:      bool = True


class ConnectorIn(BaseModel):
    project_id:     int
    connector_type: str
    base_url:       str | None = None
    active:         bool = True


class ConnectorSetupIn(BaseModel):
    """Combined connector + credentials — for the Add/Edit Connector pages."""
    project_id:     int
    connector_type: str
    base_url:       str | None = None
    credentials:    dict[str, str] = {}   # key → plaintext value (encrypted on write)
    updated_by:     str | None = None


class CredentialIn(BaseModel):
    project_id:     int
    connector_type: str
    key:            str
    value:          str          # plaintext — encrypted on write, never returned
    updated_by:     str | None = None


class OperationIn(BaseModel):
    project_id:     int
    connector_id:   int
    connector_type: str
    operation_name: str
    endpoint:       str
    method:         str = "POST"
    description:    str | None = None
    active:         bool = True


# ── Projects ──────────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = db.query(Project).order_by(Project.id).all()
    return [_proj(r) for r in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    if db.query(Project).filter_by(slug=body.slug).first():
        raise HTTPException(409, f"Project slug '{body.slug}' already exists")
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _proj(p)


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter_by(id=project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    return _proj(p)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectIn, db: Session = Depends(get_db)):
    p = db.query(Project).filter_by(id=project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _proj(p)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter_by(id=project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    db.delete(p)
    db.commit()


# ── Connectors ────────────────────────────────────────────────────────────────

@router.get("/connectors")
def list_connectors(project_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(ConnectorConfig)
    if project_id:
        q = q.filter_by(project_id=project_id)
    return [_conn(r) for r in q.all()]


@router.post("/connectors", status_code=201)
def create_connector(body: ConnectorIn, db: Session = Depends(get_db)):
    c = ConnectorConfig(**body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return _conn(c)


@router.patch("/connectors/{connector_id}")
def update_connector(connector_id: int, body: ConnectorIn, db: Session = Depends(get_db)):
    c = db.query(ConnectorConfig).filter_by(id=connector_id).first()
    if not c:
        raise HTTPException(404, "Connector not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _conn(c)


@router.post("/connectors/setup", status_code=201)
def setup_connector(body: ConnectorSetupIn, db: Session = Depends(get_db)):
    """Create connector + all credentials in one transaction."""
    c = ConnectorConfig(
        project_id     = body.project_id,
        connector_type = body.connector_type,
        base_url       = body.base_url,
        active         = True,
    )
    db.add(c)
    db.flush()
    for key, val in body.credentials.items():
        if not val:
            continue
        db.add(Credential(
            project_id      = body.project_id,
            connector_type  = body.connector_type,
            key             = key,
            value_encrypted = encrypt(val),
            updated_by      = body.updated_by or "ui",
        ))
    # Seed default operations for known connector types
    ops_seeded = 0
    for op_def in _DEFAULT_OPS.get(body.connector_type, []):
        db.add(Operation(
            project_id     = body.project_id,
            connector_id   = c.id,
            connector_type = body.connector_type,
            active         = True,
            **op_def,
        ))
        ops_seeded += 1

    db.commit()
    db.refresh(c)
    return {**_conn(c), "credentials_saved": len(body.credentials), "operations_seeded": ops_seeded}


@router.patch("/connectors/{connector_id}/setup")
def update_connector_setup(connector_id: int, body: ConnectorSetupIn,
                           db: Session = Depends(get_db)):
    """Update connector config + upsert credentials in one transaction."""
    c = db.query(ConnectorConfig).filter_by(id=connector_id).first()
    if not c:
        raise HTTPException(404, "Connector not found")
    if body.base_url is not None:
        c.base_url = body.base_url
    for key, val in body.credentials.items():
        if not val:
            continue
        existing = (db.query(Credential)
                    .filter_by(project_id=c.project_id,
                               connector_type=c.connector_type, key=key)
                    .first())
        if existing:
            existing.value_encrypted = encrypt(val)
            existing.updated_by      = body.updated_by or "ui"
        else:
            db.add(Credential(
                project_id      = c.project_id,
                connector_type  = c.connector_type,
                key             = key,
                value_encrypted = encrypt(val),
                updated_by      = body.updated_by or "ui",
            ))
    db.commit()
    db.refresh(c)
    return {**_conn(c), "credentials_saved": len(body.credentials)}


class TestConnectorIn(BaseModel):
    connector_type: str
    credentials:    dict[str, str] = {}


@router.post("/connectors/test")
def test_connector(body: TestConnectorIn):
    """Test a connector with supplied credentials (before or after save)."""
    from app.core.registry import get_connector
    try:
        conn = get_connector(body.connector_type)
        ok   = conn.health_check(body.credentials)
        return {"healthy": ok, "connector": body.connector_type}
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        return {"healthy": False, "connector": body.connector_type, "error": str(exc)}


@router.post("/connectors/generate-plugin")
def generate_plugin(connector_type: str):
    """
    Generate a generic REST connector .py file for an unknown connector type.
    Safe to call — will not overwrite an existing file.
    """
    safe_name = re.sub(r"[^a-z0-9_]", "_", connector_type.lower())
    path      = os.path.join(
        os.path.dirname(__file__), "..", "connectors", f"{safe_name}.py"
    )
    path = os.path.normpath(path)

    if os.path.exists(path):
        return {"created": False, "path": path, "reason": "file already exists"}

    class_name = "".join(w.capitalize() for w in safe_name.split("_")) + "Connector"
    code = textwrap.dedent(f'''\
        """
        {connector_type} connector plugin — auto-generated by AVIS Connect.
        Edit this file to customise auth, headers, and response handling.

        Credential keys (stored encrypted in connect.credentials):
          api_key   — API key or Bearer token
          base_url  — Base URL of the API
          (add more keys as needed via Edit Connector)
        """
        from __future__ import annotations

        import logging
        from typing import Any

        import requests

        from app.connectors.base import BaseConnector

        log = logging.getLogger(__name__)


        class {class_name}(BaseConnector):
            """{connector_type} REST connector."""

            name = "{safe_name}"

            def execute(
                self,
                operation: str,
                endpoint: str,
                method: str,
                payload: dict[str, Any],
                credentials: dict[str, str],
            ) -> dict:
                base_url = credentials.get("base_url", "").rstrip("/")
                api_key  = credentials.get("api_key", "")

                url  = endpoint if endpoint.startswith("http") else f"{{base_url}}{{endpoint}}"
                verb = method.upper()

                headers = {{
                    "Authorization": f"Bearer {{api_key}}",
                    "Content-Type":  "application/json",
                    "Accept":        "application/json",
                }}

                log.info("{connector_type} %s %s [op=%s]", verb, url, operation)

                if verb == "GET":
                    resp = requests.get(url, params=payload or None, headers=headers, timeout=30)
                elif verb == "POST":
                    resp = requests.post(url, json=payload, headers=headers, timeout=30)
                elif verb == "PATCH":
                    resp = requests.patch(url, json=payload, headers=headers, timeout=30)
                elif verb == "DELETE":
                    resp = requests.delete(url, headers=headers, timeout=30)
                else:
                    raise ValueError(f"Unsupported method: {{method}}")

                if resp.status_code not in (200, 201, 204):
                    raise RuntimeError(
                        f"{connector_type} {{resp.status_code}} for op={{operation}}: {{resp.text[:400]}}"
                    )

                try:
                    return resp.json()
                except Exception:
                    return {{"raw": resp.text, "status_code": resp.status_code}}

            def health_check(self, credentials: dict[str, str]) -> bool:
                try:
                    base_url = credentials.get("base_url", "").rstrip("/")
                    api_key  = credentials.get("api_key", "")
                    resp = requests.get(
                        base_url,
                        headers={{"Authorization": f"Bearer {{api_key}}", "Accept": "application/json"}},
                        timeout=10,
                    )
                    return resp.status_code < 500
                except Exception as exc:
                    log.warning("{connector_type} health check failed: %s", exc)
                    return False
    ''')

    with open(path, "w") as f:
        f.write(code)

    # Invalidate registry cache so new plugin is picked up immediately
    from app.core import registry as _reg
    _reg._registry.clear()

    return {"created": True, "path": path, "class": class_name}


@router.get("/connectors/{connector_id}/detail")
def connector_detail(connector_id: int, db: Session = Depends(get_db)):
    """Return connector config + credential keys (never plaintext values)."""
    c = db.query(ConnectorConfig).filter_by(id=connector_id).first()
    if not c:
        raise HTTPException(404, "Connector not found")
    keys = (db.query(Credential)
            .filter_by(project_id=c.project_id, connector_type=c.connector_type)
            .all())
    return {
        **_conn(c),
        "credential_keys": [
            {"key": k.key, "has_value": bool(k.value_encrypted),
             "updated_at": k.updated_at.isoformat() if k.updated_at else None}
            for k in keys
        ],
    }


# ── Credentials (write-only — value never returned in plaintext) ───────────────

@router.post("/credentials", status_code=201)
def upsert_credential(body: CredentialIn, db: Session = Depends(get_db)):
    """Upsert a credential key. Value is encrypted before storage and never returned."""
    existing = (db.query(Credential)
                .filter_by(project_id=body.project_id,
                           connector_type=body.connector_type,
                           key=body.key)
                .first())
    encrypted = encrypt(body.value)
    if existing:
        existing.value_encrypted = encrypted
        if body.updated_by:
            existing.updated_by = body.updated_by
        db.commit()
        return {"updated": True, "key": body.key}
    else:
        row = Credential(
            project_id     = body.project_id,
            connector_type = body.connector_type,
            key            = body.key,
            value_encrypted= encrypted,
            updated_by     = body.updated_by,
        )
        db.add(row)
        db.commit()
        return {"created": True, "key": body.key}


@router.delete("/credentials")
def delete_credential(project_id: int, connector_type: str, key: str,
                      db: Session = Depends(get_db)):
    row = (db.query(Credential)
           .filter_by(project_id=project_id, connector_type=connector_type, key=key)
           .first())
    if not row:
        raise HTTPException(404, "Credential not found")
    db.delete(row)
    db.commit()
    return {"deleted": True, "key": key}


@router.get("/credentials/reveal")
def reveal_credential(project_id: int, connector_type: str, key: str,
                      db: Session = Depends(get_db)):
    """Return the decrypted value for a single credential (admin only)."""
    row = (db.query(Credential)
           .filter_by(project_id=project_id, connector_type=connector_type, key=key)
           .first())
    if not row:
        raise HTTPException(404, "Credential not found")
    try:
        return {"key": row.key, "value": decrypt(row.value_encrypted)}
    except Exception:
        raise HTTPException(500, "Failed to decrypt credential")


@router.get("/credentials/keys")
def list_credential_keys(project_id: int, connector_type: str,
                         db: Session = Depends(get_db)):
    """Return only the key names (never plaintext values) for a project+connector."""
    rows = (db.query(Credential)
            .filter_by(project_id=project_id, connector_type=connector_type)
            .all())
    return [{"key": r.key, "updated_at": r.updated_at.isoformat() if r.updated_at else None,
             "updated_by": r.updated_by} for r in rows]


# ── Operations ────────────────────────────────────────────────────────────────

@router.get("/operations")
def list_operations(project_id: int | None = None, connector_type: str | None = None,
                    db: Session = Depends(get_db)):
    q = db.query(Operation)
    if project_id:
        q = q.filter_by(project_id=project_id)
    if connector_type:
        q = q.filter_by(connector_type=connector_type)
    return [_op(r) for r in q.all()]


@router.post("/operations", status_code=201)
def create_operation(body: OperationIn, db: Session = Depends(get_db)):
    o = Operation(**body.model_dump())
    db.add(o)
    db.commit()
    db.refresh(o)
    return _op(o)


@router.patch("/operations/{op_id}")
def update_operation(op_id: int, body: OperationIn, db: Session = Depends(get_db)):
    o = db.query(Operation).filter_by(id=op_id).first()
    if not o:
        raise HTTPException(404, "Operation not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    db.commit()
    db.refresh(o)
    return _op(o)


@router.delete("/operations/{op_id}", status_code=204)
def delete_operation(op_id: int, db: Session = Depends(get_db)):
    o = db.query(Operation).filter_by(id=op_id).first()
    if not o:
        raise HTTPException(404, "Operation not found")
    db.delete(o)
    db.commit()


# ── Serializers ───────────────────────────────────────────────────────────────

def _proj(p: Project) -> dict:
    return {"id": p.id, "slug": p.slug, "name": p.name,
            "description": p.description, "active": p.active,
            "created_at": p.created_at.isoformat() if p.created_at else None}


def _conn(c: ConnectorConfig) -> dict:
    return {"id": c.id, "project_id": c.project_id, "connector_type": c.connector_type,
            "base_url": c.base_url, "active": c.active,
            "created_at": c.created_at.isoformat() if c.created_at else None}


def _op(o: Operation) -> dict:
    return {"id": o.id, "project_id": o.project_id, "connector_id": o.connector_id,
            "connector_type": o.connector_type, "operation_name": o.operation_name,
            "endpoint": o.endpoint, "method": o.method,
            "description": o.description, "active": o.active}
