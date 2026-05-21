"""Jinja2-rendered HTML routes for the AVIS Connect admin web interface."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import registry
from app.db import get_db
from app.models import ConnectorConfig, Operation, Project, PushLog

# ── Plugin metadata — displayed on the Connectors reference page ──────────────
_PLUGIN_META: dict[str, dict] = {
    "netsuite": {
        "auth":        "OAuth 1.0a Token-Based Auth (TBA)",
        "description": "NetSuite SuiteTalk REST API. Supports job/project, resource allocation, sales order, invoice, and journal entry operations.",
        "credential_keys": ["account_id", "consumer_key", "consumer_secret", "token_id", "token_secret"],
        "operations": [
            {"name": "create_allocation", "method": "POST", "endpoint": "/projectresource",
             "description": "Push resource allocation after BU Head approval",
             "payload_template": {
                 "externalid": "ALLOC-1234", "resource": "EMP-2029",
                 "project": "1234", "projecttask": "2466",
                 "startdate": "01/06/2026", "enddate": "31/12/2026",
                 "allocationby": "PercentOfTime", "allocation": "40",
                 "allocationtype": "Hard", "allocationcategory": "Billable",
             }},
            {"name": "create_so", "method": "POST", "endpoint": "/salesorder",
             "description": "Create Sales Order after RevOps + BFM approval",
             "payload_template": {
                 "body": {
                     "externalid": "SO-RMS-001", "customer": "NS_CUSTOMER_ID",
                     "trandate": "18/05/2026", "project": "NS_PROJECT_ID",
                     "startdate": "01/06/2026", "enddate": "31/12/2026",
                     "currency": "1", "subsidiary": "1",
                     "salesorderbillingtype": "Milestone",
                 },
                 "items": [
                     {"item": "NS_ITEM_ID", "quantity": 1, "rate": 5000,
                      "amount": 5000, "description": "Engineering services"},
                 ],
             }},
            {"name": "create_invoice", "method": "POST", "endpoint": "/invoice",
             "description": "Generate invoice after timesheet compliance confirmed",
             "payload_template": {
                 "externalid": "INV-RMS-001", "salesorderid": "NS_SO_INTERNAL_ID",
                 "items": [
                     {"item": "NS_ITEM_ID", "quantity": 1, "rate": 5000,
                      "amount": 5000, "solineid": "NS_SO_LINE_ID"},
                 ],
             }},
            {"name": "create_journal", "method": "POST", "endpoint": "/journalentry",
             "description": "Post GL journal entry after invoice approved",
             "payload_template": {
                 "externalid": "JE-RMS-001", "trandate": "18/05/2026",
                 "subsidiary": "1", "currency": "1", "memo": "Revenue recognition",
                 "line": {"items": [
                     {"account": "GL_ACCOUNT_ID", "type": "debit",  "amount": 5000, "memo": "Revenue"},
                     {"account": "GL_ACCOUNT_ID", "type": "credit", "amount": 5000, "memo": "Deferred"},
                 ]},
             }},
            {"name": "get_project", "method": "GET", "endpoint": "/job",
             "description": "Fetch NS Job record by externalId",
             "payload_template": {"q": 'externalId IS "PROJ-123"'}},
        ],
        "payload_examples": [
            {"label": "create_allocation", "json": json.dumps({
                "externalid": "ALLOC-1234", "resource": "EMP-2029",
                "project": "1234", "projecttask": "2466",
                "startdate": "01/06/2026", "enddate": "31/12/2026",
                "allocationby": "PercentOfTime", "allocation": "40",
                "allocationtype": "Hard", "allocationcategory": "Billable",
            }, indent=2)},
            {"label": "get_project", "json": json.dumps(
                {"q": 'externalId IS "PROJ-123"'}, indent=2)},
        ],
    },
    "salesforce": {
        "auth":        "Username + Password + Security Token",
        "description": "Salesforce REST API via simple-salesforce. Supports SOQL queries and full SObject CRUD. Primary use: write NS Sales Order IDs back to Opportunity after push.",
        "credential_keys": ["username", "password", "security_token"],
        "operations": [
            {"name": "query", "method": "GET", "endpoint": "query",
             "description": "SOQL SELECT — pass {\"q\": \"SELECT ...\"}",
             "payload_template": {
                 "q": "SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity ORDER BY CloseDate DESC LIMIT 10",
             }},
            {"name": "get_opportunity", "method": "GET", "endpoint": "Opportunity",
             "description": "Fetch one Opportunity by SF Id",
             "payload_template": {"sf_id": "006gK00000HoKHtQAN"}},
            {"name": "so_writeback", "method": "PATCH", "endpoint": "Opportunity",
             "description": "Write NS Sales Order number back to SFDC after SO push",
             "payload_template": {
                 "sf_id": "006gK00000HoKHtQAN",
                 "NS_Sales_Order_Mapping__c": "SO-12345",
             }},
            {"name": "invoice_writeback", "method": "PATCH", "endpoint": "Opportunity",
             "description": "Write NS Invoice ID back to SFDC after invoice push",
             "payload_template": {
                 "sf_id": "006gK00000HoKHtQAN",
                 "NS_Invoice_ID__c": "INV-001",
             }},
            {"name": "create_opportunity", "method": "POST", "endpoint": "Opportunity",
             "description": "Create new Opportunity record",
             "payload_template": {
                 "Name": "New Opportunity", "AccountId": "SF_ACCOUNT_ID",
                 "StageName": "Prospecting", "CloseDate": "2026-12-31",
                 "Amount": 100000,
             }},
            {"name": "get_10_opportunities", "method": "GET", "endpoint": "query",
             "description": "Sample 10 Opportunities — quick test query",
             "payload_template": {
                 "q": "SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity LIMIT 10",
             }},
            {"name": "get_opportunities", "method": "GET", "endpoint": "query",
             "description": "List open Opportunities via SOQL",
             "payload_template": {
                 "q": "SELECT Id, Name, StageName, Amount, CloseDate, AccountId, OwnerId, Probability FROM Opportunity WHERE StageName != 'Closed Lost' ORDER BY CloseDate ASC LIMIT 20",
             }},
            {"name": "get_contacts", "method": "GET", "endpoint": "query",
             "description": "List Contacts via SOQL",
             "payload_template": {
                 "q": "SELECT Id, FirstName, LastName, Email, Phone, Title, AccountId, Department, MailingCountry FROM Contact WHERE Email != null ORDER BY LastName ASC LIMIT 20",
             }},
            {"name": "get_leads", "method": "GET", "endpoint": "query",
             "description": "List open (unconverted) Leads via SOQL",
             "payload_template": {
                 "q": "SELECT Id, FirstName, LastName, Company, Title, Email, Phone, Status, LeadSource, Industry, CreatedDate FROM Lead WHERE IsConverted = false ORDER BY CreatedDate DESC LIMIT 20",
             }},
        ],
        "payload_examples": [
            {"label": "SOQL query", "json": json.dumps({
                "q": "SELECT Id, Name, StageName, Amount FROM Opportunity WHERE StageName = 'Closed Won' LIMIT 10",
            }, indent=2)},
            {"label": "so_writeback", "json": json.dumps({
                "sf_id": "006gK00000HoKHtQAN",
                "NS_Sales_Order_Mapping__c": "SO-12345",
            }, indent=2)},
        ],
    },
}

router    = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    total_logs   = db.query(func.count(PushLog.id)).scalar() or 0
    success_logs = db.query(func.count(PushLog.id)).filter_by(status="success").scalar() or 0
    error_logs   = db.query(func.count(PushLog.id)).filter_by(status="error").scalar() or 0
    recent_logs  = (db.query(PushLog)
                    .order_by(PushLog.created_at.desc())
                    .limit(20).all())
    projects     = db.query(Project).filter_by(active=True).order_by(Project.name).all()
    connectors   = registry.list_connectors()

    return templates.TemplateResponse("dashboard.html", {
        "request":      request,
        "total_logs":   total_logs,
        "success_logs": success_logs,
        "error_logs":   error_logs,
        "recent_logs":  recent_logs,
        "projects":     projects,
        "connectors":   connectors,
    })


@router.get("/projects", response_class=HTMLResponse)
def projects_list(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse("projects/list.html", {
        "request":  request,
        "projects": projects,
    })


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        return HTMLResponse("<h3>Project not found</h3>", status_code=404)
    connectors   = (db.query(ConnectorConfig)
                    .filter_by(project_id=project_id).all())
    operations   = (db.query(Operation)
                    .filter_by(project_id=project_id).all())
    recent_logs  = (db.query(PushLog)
                    .filter_by(project_id=project_id)
                    .order_by(PushLog.created_at.desc())
                    .limit(10).all())
    plugin_names = registry.list_connectors()
    return templates.TemplateResponse("projects/detail.html", {
        "request":      request,
        "project":      project,
        "connectors":   connectors,
        "operations":   operations,
        "recent_logs":  recent_logs,
        "plugin_names": plugin_names,
    })


@router.get("/logs", response_class=HTMLResponse)
def logs_list(request: Request,
              project: str | None = None,
              connector: str | None = None,
              status: str | None = None,
              db: Session = Depends(get_db)):
    q = db.query(PushLog).order_by(PushLog.created_at.desc())
    if project:
        q = q.filter(PushLog.project_slug == project)
    if connector:
        q = q.filter(PushLog.connector_type == connector)
    if status:
        q = q.filter(PushLog.status == status)
    logs     = q.limit(100).all()
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse("logs/list.html", {
        "request":   request,
        "logs":      logs,
        "projects":  projects,
        "filter_project":   project   or "",
        "filter_connector": connector or "",
        "filter_status":    status    or "",
    })


@router.get("/logs/{log_id}", response_class=HTMLResponse)
def log_detail(log_id: int, request: Request, db: Session = Depends(get_db)):
    log = db.query(PushLog).filter_by(id=log_id).first()
    if not log:
        return HTMLResponse("<h3>Log entry not found</h3>", status_code=404)
    payload_fmt  = json.dumps(json.loads(log.payload_json  or "{}"), indent=2)
    response_fmt = json.dumps(json.loads(log.response_json or "{}"), indent=2)
    return templates.TemplateResponse("logs/detail.html", {
        "request":      request,
        "log":          log,
        "payload_fmt":  payload_fmt,
        "response_fmt": response_fmt,
    })


@router.get("/execute", response_class=HTMLResponse)
def execute_ui(request: Request, db: Session = Depends(get_db)):
    import os, base64
    user = os.getenv("CONNECT_ADMIN_USER", "admin")
    pw   = os.getenv("CONNECT_ADMIN_PASSWORD", "")
    admin_b64 = base64.b64encode(f"{user}:{pw}".encode()).decode()
    projects = db.query(Project).filter_by(active=True).order_by(Project.name).all()

    # Build payload_templates: {"connector:operation_name": {...template...}}
    payload_templates: dict[str, dict] = {}
    for connector_name, meta in _PLUGIN_META.items():
        for op in meta.get("operations", []):
            if "payload_template" in op:
                key = f"{connector_name}:{op['name']}"
                payload_templates[key] = op["payload_template"]

    return templates.TemplateResponse("execute.html", {
        "request":           request,
        "projects":          projects,
        "admin_b64":         admin_b64,
        "payload_templates": json.dumps(payload_templates),
    })


@router.get("/health", response_class=HTMLResponse)
def health_ui(request: Request, db: Session = Depends(get_db)):
    conns = (db.query(ConnectorConfig)
             .join(Project, ConnectorConfig.project_id == Project.id)
             .filter(ConnectorConfig.active == True, Project.active == True)
             .all())
    rows = [
        {
            "project_id":     c.project_id,
            "project_slug":   c.project.slug,
            "connector_type": c.connector_type,
        }
        for c in conns
    ]
    return templates.TemplateResponse("health.html", {
        "request":   request,
        "rows":      rows,
        "rows_json": json.dumps(rows),
        "plugins":   registry.list_connectors(),
    })


@router.get("/connectors", response_class=HTMLResponse)
def connectors_list(request: Request, db: Session = Depends(get_db)):
    """Management list — all configured connectors across all projects."""
    rows = (db.query(ConnectorConfig)
            .join(Project, ConnectorConfig.project_id == Project.id)
            .order_by(Project.name, ConnectorConfig.connector_type)
            .all())
    from app.models import Credential
    from sqlalchemy import func as sqlfunc
    cred_counts = {
        (pid, ct): n
        for pid, ct, n in db.query(
            Credential.project_id, Credential.connector_type,
            sqlfunc.count(Credential.id)
        ).group_by(Credential.project_id, Credential.connector_type).all()
    }
    connectors = []
    for c in rows:
        connectors.append({
            "id":             c.id,
            "project_id":     c.project_id,
            "project_slug":   c.project.slug,
            "connector_type": c.connector_type,
            "base_url":       c.base_url,
            "active":         c.active,
            "cred_count":     cred_counts.get((c.project_id, c.connector_type), 0),
        })
    return templates.TemplateResponse("connectors/list.html", {
        "request":    request,
        "connectors": connectors,
    })


@router.get("/connectors/add", response_class=HTMLResponse)
def connector_add_form(request: Request, db: Session = Depends(get_db)):
    projects     = db.query(Project).filter_by(active=True).order_by(Project.name).all()
    plugin_names = registry.list_connectors()
    cred_keys    = {name: _PLUGIN_META.get(name, {}).get("credential_keys", [])
                    for name in plugin_names}
    return templates.TemplateResponse("connectors/add.html", {
        "request":          request,
        "projects":         projects,
        "plugin_names":     plugin_names,
        "cred_keys_json":   json.dumps(cred_keys),
        "plugin_names_json": json.dumps(plugin_names),
    })


@router.get("/connectors/{connector_id}/edit", response_class=HTMLResponse)
def connector_edit_form(connector_id: int, request: Request, db: Session = Depends(get_db)):
    from app.models import Credential
    c = db.query(ConnectorConfig).filter_by(id=connector_id).first()
    if not c:
        return HTMLResponse("<h3>Connector not found</h3>", status_code=404)

    # Known keys for this connector type from plugin meta
    known_keys = _PLUGIN_META.get(c.connector_type, {}).get("credential_keys", [])

    # Existing credential keys in DB (may include extras beyond known_keys)
    saved_keys = (db.query(Credential)
                  .filter_by(project_id=c.project_id, connector_type=c.connector_type)
                  .all())
    saved_key_names = {k.key for k in saved_keys}

    # For known connector types respect current metadata — don't surface stale DB keys.
    # For unknown/custom types show whatever was saved.
    if c.connector_type in _PLUGIN_META:
        all_keys = list(known_keys)
    else:
        all_keys = list(known_keys) + [k for k in saved_key_names if k not in known_keys]

    cred_keys = [
        {"key": k, "has_value": k in saved_key_names}
        for k in all_keys
    ]

    return templates.TemplateResponse("connectors/edit.html", {
        "request":       request,
        "connector": {
            "id":             c.id,
            "project_id":     c.project_id,
            "project_slug":   c.project.slug,
            "connector_type": c.connector_type,
            "base_url":       c.base_url,
            "active":         c.active,
        },
        "cred_keys":      cred_keys,
        "known_keys_json": json.dumps(all_keys),
    })
