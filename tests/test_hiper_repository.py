import json
import sqlite3
import time

import pytest

from app.automation.hiper.errors import HiperDeploymentAlreadyRunning
from app.automation.hiper.resolver import HiperStore
from app.persistence.db import init_db, connect
from app.persistence.hiper import HiperRepository
from app.persistence.repositories import DeploymentRepository, StepRepository


def test_additive_migration_preserves_old_deployment(tmp_path):
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE deployments(id INTEGER PRIMARY KEY,contract_id TEXT,
            hiper_account TEXT,environment TEXT,status TEXT,data_json TEXT,created_at TEXT,
            updated_at TEXT,approved_by TEXT,approved_at TEXT)""")
        db.execute("INSERT INTO deployments VALUES(1,'1042',NULL,'homologacao','rascunho','{}','now','now',NULL,NULL)")
    init_db(path)
    init_db(path)
    row = DeploymentRepository(path).get(1)
    assert row.contract_id == "1042" and row.execution_mode == "simulation"
    assert len(StepRepository(path).list_for_deployment(1)) == 7


def test_lock_conflict_owner_and_expiry(app):
    repository = HiperRepository(app.config["DATABASE"])
    repository.acquire("tenant:one", "owner-a")
    with pytest.raises(HiperDeploymentAlreadyRunning):
        HiperRepository(app.config["DATABASE"]).acquire("tenant:one", "owner-b")
    repository.release("tenant:one", "wrong-owner")
    with pytest.raises(HiperDeploymentAlreadyRunning):
        repository.renew("tenant:one", "wrong-owner")
    repository.renew("tenant:one", "owner-a")
    repository.release("tenant:one", "owner-a")
    repository.acquire("tenant:one", "expired", ttl=-1)
    repository.acquire("tenant:one", "new-owner")


def test_persists_mapping_and_context(app):
    deployments = DeploymentRepository(app.config["DATABASE"])
    deployment = deployments.create("1042", {"company": {"cnpj": "12345678000195"}})
    repository = HiperRepository(app.config["DATABASE"])
    store = HiperStore("id", "Empresa", "12345678000195", "https://one.hiper.com.br/settings")
    repository.context(deployment.id, "https://one.hiper.com.br", store)
    result = deployments.get(deployment.id)
    assert result.hiper_store_id == "id"
    assert result.store_verified_at and result.hiper_store_cnpj == "12345678000195"
    assert repository.mapping("1042", "12345678000195", "https://one.hiper.com.br") == "id"


def test_review_during_execution_is_rejected_and_identity_change_invalidates(app):
    deployments = DeploymentRepository(app.config["DATABASE"])
    repository = HiperRepository(app.config["DATABASE"])
    deployment = deployments.create("1042", {"company": {"cnpj": "12345678000195"}})
    repository.context(deployment.id, "https://one.hiper.com.br", HiperStore("one", "Name", "12345678000195", "https://one.hiper.com.br"))
    repository.acquire(f"deployment:{deployment.id}", "active")
    with pytest.raises(HiperDeploymentAlreadyRunning):
        deployments.update_review(deployment.id, deployment.data)
    repository.release(f"deployment:{deployment.id}", "active")
    deployments.update_review(deployment.id, {"company": {"cnpj": "11222333000144"}})
    assert deployments.get(deployment.id).hiper_store_id is None
