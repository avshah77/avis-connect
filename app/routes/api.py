"""
AVIS Connect — API routes.

POST /api/execute        Execute an operation via a connector plugin
GET  /api/logs           Query push_log (filterable by project/connector/status)
GET  /api/logs/{id}      Single push_log entry with full payload + response
GET  /api/connectors     List registered connector plugin names
GET  /api/health/{connector_type}/{project_slug}  Liveness check
POST /api/retry/{log_id} Retry a failed execution with original payload

Salesforce shortcuts:
GET  /api/salesforce/{project_slug}/opportunities   List open opportunities
GET  /api/salesforce/{project_slug}/accounts        List accounts
GET  /api/salesforce/{project_slug}/leads           List open (unconverted) leads
GET  /api/salesforce/{project_slug}/contacts        List contacts
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import engine, registry
from app.core.crypto import decrypt
from app.db import get_db
from app.models import Credential, PushLog

router = APIRouter(prefix="/api", tags=["api"])


# ── Request / Response models ─────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    project:    str
    connector:  str
    operation:  str
    payload:    dict[str, Any] = {}
    retry_of:   int | None = None


class ExecuteResponse(BaseModel):
    success:     bool
    log_id:      int | None
    response:    dict | None
    error:       str | None
    duration_ms: float


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/execute", response_model=ExecuteResponse)
def execute(body: ExecuteRequest, db: Session = Depends(get_db)):
    result = engine.execute(
        db             = db,
        project_slug   = body.project,
        connector_type = body.connector,
        operation_name = body.operation,
        payload        = body.payload,
        retry_of       = body.retry_of,
    )
    if not result.success:
        # Return 422 so callers can distinguish infra errors from business errors
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={
            "success":     False,
            "log_id":      result.log_id,
            "response":    None,
            "error":       result.error,
            "duration_ms": result.duration_ms,
        })
    return ExecuteResponse(
        success     = result.success,
        log_id      = result.log_id,
        response    = result.response,
        error       = result.error,
        duration_ms = result.duration_ms,
    )


@router.post("/retry/{log_id}", response_model=ExecuteResponse)
def retry(log_id: int, db: Session = Depends(get_db)):
    original = db.query(PushLog).filter_by(id=log_id).first()
    if not original:
        raise HTTPException(404, f"Log entry {log_id} not found")
    if original.status == "success":
        raise HTTPException(400, "Cannot retry a successful execution")

    payload = json.loads(original.payload_json or "{}")
    result = engine.execute(
        db             = db,
        project_slug   = original.project_slug,
        connector_type = original.connector_type,
        operation_name = original.operation,
        payload        = payload,
        retry_of       = log_id,
    )
    return ExecuteResponse(
        success     = result.success,
        log_id      = result.log_id,
        response    = result.response,
        error       = result.error,
        duration_ms = result.duration_ms,
    )


@router.get("/logs")
def list_logs(
    project:   str | None = None,
    connector: str | None = None,
    status:    str | None = None,
    limit:     int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(PushLog).order_by(PushLog.created_at.desc())
    if project:
        q = q.filter(PushLog.project_slug == project)
    if connector:
        q = q.filter(PushLog.connector_type == connector)
    if status:
        q = q.filter(PushLog.status == status)
    rows = q.limit(min(limit, 500)).all()
    return [_log_summary(r) for r in rows]


@router.get("/logs/{log_id}")
def get_log(log_id: int, db: Session = Depends(get_db)):
    row = db.query(PushLog).filter_by(id=log_id).first()
    if not row:
        raise HTTPException(404, f"Log {log_id} not found")
    return {
        **_log_summary(row),
        "payload":  json.loads(row.payload_json  or "{}"),
        "response": json.loads(row.response_json or "{}"),
    }


@router.get("/connectors")
def list_available_connectors():
    return {"connectors": registry.list_connectors()}


@router.get("/health/{connector_type}/{project_slug}")
def health_check(connector_type: str, project_slug: str, db: Session = Depends(get_db)):
    from app.models import Project
    project = db.query(Project).filter_by(slug=project_slug, active=True).first()
    if not project:
        raise HTTPException(404, f"Project '{project_slug}' not found")

    cred_rows = (db.query(Credential)
                 .filter_by(project_id=project.id, connector_type=connector_type)
                 .all())
    credentials = {}
    for row in cred_rows:
        try:
            credentials[row.key] = decrypt(row.value_encrypted)
        except Exception:
            credentials[row.key] = ""

    try:
        connector = registry.get_connector(connector_type)
        ok = connector.health_check(credentials)
    except Exception as exc:
        return {"healthy": False, "error": str(exc)}

    return {"healthy": ok, "connector": connector_type, "project": project_slug}


# ── Salesforce shortcuts ──────────────────────────────────────────────────────

router_sf = APIRouter(prefix="/api/salesforce", tags=["salesforce"])


def _sf_query(db: Session, project_slug: str, soql: str) -> dict:
    """Run a SOQL query via the Salesforce connector and return the raw response."""
    result = engine.execute(
        db             = db,
        project_slug   = project_slug,
        connector_type = "salesforce",
        operation_name = "query",
        payload        = {"q": soql},
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error or "Salesforce query failed")
    return result.response or {}


@router_sf.get("/opportunities",
               summary="List Salesforce Opportunities",
               description="Returns open Opportunities from Salesforce.")
def sf_opportunities(
    project: str = "rms-tessolve",
    limit: int = 20,
    stage: str | None = None,
    db: Session = Depends(get_db),
):
    where = "StageName != 'Closed Lost'"
    if stage:
        where = f"StageName = '{stage}'"
    soql = (
        f"SELECT Id, Name, StageName, Amount, CloseDate, AccountId, "
        f"OwnerId, Probability "
        f"FROM Opportunity WHERE {where} "
        f"ORDER BY CloseDate ASC LIMIT {min(limit, 200)}"
    )
    data = _sf_query(db, project, soql)
    records = data.get("records", data) if isinstance(data, dict) else data
    return {"project": project, "count": len(records), "opportunities": records}


@router_sf.get("/accounts",
               summary="List Salesforce Accounts",
               description="Returns Accounts from Salesforce.")
def sf_accounts(
    project: str = "rms-tessolve",
    limit: int = 20,
    db: Session = Depends(get_db),
):
    soql = (
        f"SELECT Id, Name, Industry, BillingCountry, Phone, Website "
        f"FROM Account ORDER BY Name ASC LIMIT {min(limit, 200)}"
    )
    data = _sf_query(db, project, soql)
    records = data.get("records", data) if isinstance(data, dict) else data
    return {"project": project, "count": len(records), "accounts": records}


@router_sf.get("/leads",
               summary="List Salesforce Leads",
               description="Returns open (not converted) Leads from Salesforce.")
def sf_leads(
    project: str = "rms-tessolve",
    limit: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    where = "IsConverted = false"
    if status:
        where += f" AND Status = '{status}'"
    soql = (
        f"SELECT Id, FirstName, LastName, Company, Title, Email, Phone, "
        f"Status, LeadSource, Industry, CreatedDate "
        f"FROM Lead WHERE {where} "
        f"ORDER BY CreatedDate DESC LIMIT {min(limit, 200)}"
    )
    data = _sf_query(db, project, soql)
    records = data.get("records", data) if isinstance(data, dict) else data
    return {"project": project, "count": len(records), "leads": records}


@router_sf.get("/contacts",
               summary="List Salesforce Contacts",
               description="Returns Contacts from Salesforce.")
def sf_contacts(
    project: str = "rms-tessolve",
    limit: int = 20,
    account_id: str | None = None,
    db: Session = Depends(get_db),
):
    where = "Email != null"
    if account_id:
        where += f" AND AccountId = '{account_id}'"
    soql = (
        f"SELECT Id, FirstName, LastName, Email, Phone, Title, "
        f"AccountId, Department, MailingCountry "
        f"FROM Contact WHERE {where} "
        f"ORDER BY LastName ASC LIMIT {min(limit, 200)}"
    )
    data = _sf_query(db, project, soql)
    records = data.get("records", data) if isinstance(data, dict) else data
    return {"project": project, "count": len(records), "contacts": records}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_summary(row: PushLog) -> dict:
    return {
        "id":            row.id,
        "project":       row.project_slug,
        "connector":     row.connector_type,
        "operation":     row.operation,
        "status":        row.status,
        "http_status":   row.http_status,
        "duration_ms":   row.duration_ms,
        "error_msg":     row.error_msg,
        "retry_count":   row.retry_count,
        "original_log":  row.original_log_id,
        "created_at":    row.created_at.isoformat() if row.created_at else None,
    }
