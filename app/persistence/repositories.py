"""Persistence repositories for deployments and their steps."""

import json
import time
from datetime import datetime, timezone
from typing import Any

from app.models import AuditEvent, Deployment, DeploymentStep, STEP_KEYS
from app.persistence.db import connect
from app.security.redaction import redact_secrets, sanitize_text
from app.services.card_brands import card_brand_targets
from app.services.validation import STEP_SECTIONS
from app.automation.hiper.errors import HiperDeploymentAlreadyRunning


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeploymentRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    @staticmethod
    def _deployment(row: Any) -> Deployment:
        return Deployment(
            id=row["id"], contract_id=row["contract_id"],
            hiper_account=row["hiper_account"], environment=row["environment"],
            status=row["status"], data=json.loads(row["data_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
            approved_by=row["approved_by"], approved_at=row["approved_at"],
            **{field: row[field] for field in (
                "hiper_base_url", "hiper_store_id", "hiper_store_name", "hiper_store_cnpj",
                "hiper_store_url", "store_resolution_method", "store_verified_at",
                "execution_mode", "selected_steps_json", "pause_requested", "contract_source",
            )},
        )

    def create(self, contract_id: str, data: dict[str, Any], *, source: str = "fixture") -> Deployment:
        now = utc_now()
        safe_data = redact_secrets(data)
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """INSERT INTO deployments
                   (contract_id, data_json, created_at, updated_at, contract_source)
                   VALUES (?, ?, ?, ?, ?)""",
                (contract_id, json.dumps(safe_data, ensure_ascii=False), now, now, source),
            )
            deployment_id = cursor.lastrowid
            connection.executemany(
                """INSERT INTO deployment_steps (deployment_id, step_key)
                   VALUES (?, ?)""",
                [(deployment_id, key) for key in STEP_KEYS],
            )
        return self.get(deployment_id)

    def get(self, deployment_id: int) -> Deployment:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM deployments WHERE id = ?", (deployment_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Implantação {deployment_id} não encontrada")
        return self._deployment(row)

    def list_all(self) -> list[Deployment]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM deployments ORDER BY id DESC"
            ).fetchall()
        return [self._deployment(row) for row in rows]

    def update_review(self, deployment_id: int, data: dict[str, Any]) -> None:
        safe_data = redact_secrets(data)
        with connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute("SELECT 1 FROM hiper_locks WHERE resource=? AND expires_at>?",
                                        (f"deployment:{deployment_id}", time.time())).fetchone()
            if active:
                raise HiperDeploymentAlreadyRunning("Pause e aguarde a execução terminar antes de editar a revisão.")
            row = connection.execute(
                "SELECT data_json FROM deployments WHERE id = ?", (deployment_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Implantação {deployment_id} não encontrada")
            previous_data = json.loads(row["data_json"])
            connection.execute(
                """UPDATE deployments
                   SET data_json = ?, status = 'aguardando_confirmacao_conta',
                       updated_at = ? WHERE id = ?""",
                (json.dumps(safe_data, ensure_ascii=False), utc_now(), deployment_id),
            )
            if card_brand_targets(previous_data) != card_brand_targets(safe_data):
                connection.execute(
                    """UPDATE deployment_steps SET status = 'pendente',
                       started_at = NULL, finished_at = NULL,
                       evidence_reference = NULL, error_code = NULL,
                       error_message_sanitized = NULL
                       WHERE deployment_id = ? AND step_key = 'config_vendas'
                       AND status = 'concluida'""",
                    (deployment_id,),
                )
            for key, sections in STEP_SECTIONS.items():
                if any(previous_data.get(section) != safe_data.get(section) for section in sections):
                    connection.execute("""UPDATE deployment_steps SET status='pendente',
                        evidence_reference=NULL,error_code=NULL,error_message_sanitized=NULL
                        WHERE deployment_id=? AND step_key=? AND status!='concluida'""", (deployment_id, key))
            old_identity = (previous_data.get("company") or {}).get("cnpj")
            new_identity = (safe_data.get("company") or {}).get("cnpj")
            tenant_changed = any(previous_data.get(key) != safe_data.get(key) for key in
                                 ("hiper_domain", "hiper_base_url", "hiper_store_id", "hiper_store_url"))
            if old_identity != new_identity or tenant_changed:
                connection.execute("""UPDATE deployments SET hiper_base_url=NULL,hiper_store_id=NULL,
                    hiper_store_name=NULL,hiper_store_cnpj=NULL,hiper_store_url=NULL,
                    store_verified_at=NULL,approved_at=NULL,store_resolution_method=NULL WHERE id=?""", (deployment_id,))

    def update_status(self, deployment_id: int, status: str) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                "UPDATE deployments SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), deployment_id),
            )

    def confirm_account(
        self, deployment_id: int, hiper_account: str, approved_by: str
    ) -> None:
        now = utc_now()
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE deployments
                   SET hiper_account = ?, approved_by = ?, approved_at = ?,
                       status = 'validado', updated_at = ? WHERE id = ?""",
                (sanitize_text(hiper_account), sanitize_text(approved_by), now, now,
                deployment_id),
            )

    def record_execution_started(self, deployment_id: int, actor: str) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """INSERT INTO audit_events (deployment_id, action, actor, occurred_at)
                   VALUES (?, 'execucao_iniciada', ?, ?)""",
                (deployment_id, sanitize_text(actor), utc_now()),
            )

    def list_audit_events(self, deployment_id: int) -> list[AuditEvent]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT * FROM audit_events WHERE deployment_id = ?
                   ORDER BY id""",
                (deployment_id,),
            ).fetchall()
        return [AuditEvent(**dict(row)) for row in rows]


class StepRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    @staticmethod
    def _step(row: Any) -> DeploymentStep:
        return DeploymentStep(**dict(row))

    def list_for_deployment(self, deployment_id: int) -> list[DeploymentStep]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT * FROM deployment_steps WHERE deployment_id = ?
                   ORDER BY id""",
                (deployment_id,),
            ).fetchall()
        return [self._step(row) for row in rows]

    def get(self, deployment_id: int, step_key: str) -> DeploymentStep:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """SELECT * FROM deployment_steps
                   WHERE deployment_id = ? AND step_key = ?""",
                (deployment_id, step_key),
            ).fetchone()
        if row is None:
            raise KeyError(f"Etapa {step_key} não encontrada")
        return self._step(row)

    def mark_running(self, deployment_id: int, step_key: str, *, mode: str = "simulation") -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE deployment_steps SET status = 'executando',
                   attempts = attempts + 1, started_at = ?, execution_mode = ?, finished_at = NULL,
                   evidence_reference = NULL, error_code = NULL,
                   error_message_sanitized = NULL
                   WHERE deployment_id = ? AND step_key = ?""",
                (utc_now(), mode, deployment_id, step_key),
            )

    def mark_completed(
        self, deployment_id: int, step_key: str, evidence_reference: str
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE deployment_steps SET status = 'concluida',
                   finished_at = ?, evidence_reference = ?
                   WHERE deployment_id = ? AND step_key = ?""",
                (utc_now(), sanitize_text(evidence_reference), deployment_id, step_key),
            )

    def mark_failed(
        self, deployment_id: int, step_key: str, error_code: str,
        message: str, *, awaiting_operator: bool = False,
    ) -> None:
        status = "aguardando_operador" if awaiting_operator else "falhou"
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE deployment_steps SET status = ?, finished_at = ?,
                   error_code = ?, error_message_sanitized = ?
                   WHERE deployment_id = ? AND step_key = ?""",
                (status, utc_now(), sanitize_text(error_code), sanitize_text(message),
                 deployment_id, step_key),
            )
