"""Additive Hiper persistence, audit trail and cross-process leases."""

import json
import time
import sqlite3
from contextlib import contextmanager

from app.automation.hiper.errors import HiperDeploymentAlreadyRunning
from app.persistence.db import connect
from app.persistence.repositories import utc_now
from app.security.redaction import sanitize_text


class HiperRepository:
    def __init__(self, database: str):
        self.database = database

    def audit(self, deployment_id: int, action: str, actor: str = "sistema"):
        with connect(self.database) as db:
            db.execute("INSERT INTO audit_events(deployment_id,action,actor,occurred_at) VALUES(?,?,?,?)",
                       (deployment_id, sanitize_text(action), sanitize_text(actor), utc_now()))

    def context(self, deployment_id: int, base: str, store):
        now = utc_now()
        with connect(self.database) as db:
            row = db.execute("SELECT contract_id,hiper_base_url,hiper_store_id FROM deployments WHERE id=?",
                             (deployment_id,)).fetchone()
            changed = (row["hiper_base_url"], row["hiper_store_id"]) != (base, store.id)
            db.execute("""UPDATE deployments SET hiper_base_url=?,hiper_store_id=?,
                       hiper_store_name=?,hiper_store_cnpj=?,hiper_store_url=?,
                       store_resolution_method=?,store_verified_at=?,updated_at=? WHERE id=?""",
                       (base, store.id, store.name, store.cnpj, store.url, store.method, now, now, deployment_id))
            if changed:
                db.execute("UPDATE deployments SET approved_at=NULL WHERE id=?", (deployment_id,))
                db.execute("""UPDATE deployment_steps SET status='pendente', evidence_reference=NULL,
                              error_code=NULL,error_message_sanitized=NULL WHERE deployment_id=?""", (deployment_id,))
            db.execute("""INSERT INTO hiper_store_mappings VALUES(?,?,?,?,?,?)
                          ON CONFLICT(contract_id,cnpj,hiper_base_url) DO UPDATE SET
                          hiper_store_id=excluded.hiper_store_id,hiper_store_name=excluded.hiper_store_name,
                          verified_at=excluded.verified_at""",
                       (row["contract_id"], store.cnpj, base, store.id, store.name, now))

    def mapping(self, contract_id: str, cnpj: str, base: str) -> str:
        with connect(self.database) as db:
            row = db.execute("SELECT hiper_store_id FROM hiper_store_mappings WHERE contract_id=? AND cnpj=? AND hiper_base_url=?",
                             (contract_id, cnpj, base)).fetchone()
        return row[0] if row else ""

    def acquire(self, resource: str, owner: str, ttl: float = 120):
        with connect(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM hiper_locks WHERE resource=? AND expires_at<?", (resource, time.time()))
            try:
                db.execute("INSERT INTO hiper_locks VALUES(?,?,?)", (resource, owner, time.time() + ttl))
            except sqlite3.IntegrityError:
                raise HiperDeploymentAlreadyRunning("Já existe execução ativa neste tenant/filial.") from None

    def renew(self, resource: str, owner: str, ttl: float = 120):
        with connect(self.database) as db:
            cursor = db.execute("UPDATE hiper_locks SET expires_at=? WHERE resource=? AND owner=? AND expires_at>?",
                                (time.time() + ttl, resource, owner, time.time()))
            if cursor.rowcount != 1:
                raise HiperDeploymentAlreadyRunning("A posse do lock de execução expirou.")

    def release(self, resource: str, owner: str):
        with connect(self.database) as db:
            db.execute("DELETE FROM hiper_locks WHERE resource=? AND owner=?", (resource, owner))

    @contextmanager
    def lock(self, resource: str, owner: str):
        self.acquire(resource, owner)
        try:
            yield
        finally:
            self.release(resource, owner)

    def plan(self, deployment_id: int, mode: str, steps: list[str]):
        with connect(self.database) as db:
            db.execute("UPDATE deployments SET execution_mode=?,selected_steps_json=?,pause_requested=0 WHERE id=?",
                       (mode, json.dumps(steps), deployment_id))

    def pause(self, deployment_id: int):
        with connect(self.database) as db:
            db.execute("UPDATE deployments SET pause_requested=1 WHERE id=?", (deployment_id,))

    def step_result(self, deployment_id: int, key: str, mode: str, status: str,
                    evidence: str = "", error_code: str = "", message: str = ""):
        with connect(self.database) as db:
            db.execute("""UPDATE deployment_steps SET status=?,execution_mode=?,finished_at=?,
                       evidence_reference=?,error_code=?,error_message_sanitized=?
                       WHERE deployment_id=? AND step_key=?""",
                       (status, mode, utc_now(), sanitize_text(evidence), error_code or None,
                        sanitize_text(message) or None, deployment_id, key))
        self.audit(deployment_id, f"etapa:{key} modo:{mode} status:{status} erro:{error_code}")
