"""
AVIS Connect — Execution Engine

Flow for every POST /api/execute call:
  1. Load project from DB
  2. Load operation definition (endpoint, method)
  3. Load + decrypt credentials for project+connector
  4. Get connector plugin from registry
  5. Execute via plugin
  6. Log full payload, response, timing, status
  7. Return result
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from connect.core import crypto, registry
from connect.models import ConnectorConfig, Credential, Operation, Project, PushLog


@dataclass
class ExecutionResult:
    success: bool
    log_id: int | None
    response: dict | None
    error: str | None
    duration_ms: float


def execute(
    db: Session,
    project_slug: str,
    connector_type: str,
    operation_name: str,
    payload: dict[str, Any],
    retry_of: int | None = None,
) -> ExecutionResult:

    project = db.query(Project).filter_by(slug=project_slug, active=True).first()
    if not project:
        return ExecutionResult(False, None, None, f"Project '{project_slug}' not found", 0)

    op = (db.query(Operation)
          .filter_by(project_id=project.id, connector_type=connector_type,
                     operation_name=operation_name, active=True)
          .first())
    if not op:
        return ExecutionResult(False, None, None,
                               f"Operation '{operation_name}' not found for {connector_type}", 0)

    cred_rows = (db.query(Credential)
                 .filter_by(project_id=project.id, connector_type=connector_type)
                 .all())
    credentials: dict[str, str] = {}
    for row in cred_rows:
        try:
            credentials[row.key] = crypto.decrypt(row.value_encrypted)
        except Exception:
            credentials[row.key] = ""

    connector = registry.get_connector(connector_type)

    log = PushLog(
        project_id     = project.id,
        project_slug   = project_slug,
        connector_type = connector_type,
        operation      = operation_name,
        payload_json   = json.dumps(payload),
        status         = "pending",
        retry_count    = 0 if retry_of is None else 1,
        original_log_id= retry_of,
    )
    db.add(log)
    db.flush()

    t0 = time.perf_counter()
    try:
        response = connector.execute(
            operation   = operation_name,
            endpoint    = op.endpoint,
            method      = op.method,
            payload     = payload,
            credentials = credentials,
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        log.response_json = json.dumps(response)
        log.status        = "success"
        log.duration_ms   = duration_ms
        db.commit()
        return ExecutionResult(True, log.id, response, None, duration_ms)

    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000
        log.status      = "error"
        log.error_msg   = str(exc)
        log.duration_ms = duration_ms
        db.commit()
        return ExecutionResult(False, log.id, None, str(exc), duration_ms)
