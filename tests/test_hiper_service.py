import asyncio
import json

import pytest

from hiper_support import local_hiper, manager_for
from app.automation.hiper.errors import HiperDeploymentAlreadyRunning, HiperStoreAmbiguous
from app.persistence.repositories import DeploymentRepository, StepRepository
from app.persistence.hiper import HiperRepository
from app.services.hiper_deployment import HiperDeploymentService
from app.persistence.db import init_db, connect


def service_for(tmp_path, manager, base):
    config = dict(manager.config)
    config.update(DATABASE=str(tmp_path / "test.db"), REAL_HIPER_AUTOMATION_ENABLED=True, HIPER_DEFAULT_DOMAIN="")
    init_db(config["DATABASE"])
    service = HiperDeploymentService(config, manager)
    data = {"company": {"cnpj": "12345678000195", "legal_name": "Empresa local", "trade_name": "Nova loja", "email": "new@example.test"}, "hiper_base_url": base}
    deployment = service.deployments.create("1042", data, source="api")
    return service, deployment


def test_resolution_run_dryrun_to_real_resume_and_locks(tmp_path, local_hiper):
    base, state = local_hiper
    async def scenario():
        manager = manager_for(tmp_path)
        service, deployment = service_for(tmp_path, manager, base)
        try:
            page = await manager.open(base)
            await page.goto(base + "/login")
            await manager.status(base)
            context = await service.resolve(deployment.id)
            assert context["store"]["id"] == "one"
            assert service.deployments.get(deployment.id).store_verified_at
            await service.start(deployment.id, mode="dry_run")
            with pytest.raises(HiperDeploymentAlreadyRunning):
                await service.start(deployment.id, mode="dry_run")
            await service.tasks[deployment.id]
            assert state["writes"] == 0
            await service.start(deployment.id, mode="real", confirmed=True, operator="Operador",
                                selected_steps=["loja_config", "usuarios"])
            await service.tasks[deployment.id]
            assert state["writes"] == 1
            assert service.deployments.get(deployment.id).status == "blocked"
            assert service.steps.get(deployment.id, "usuarios").error_code == "selector_not_mapped"
            attempts = service.steps.get(deployment.id, "loja_config").attempts
            await service.start(deployment.id, mode="real", confirmed=True, operator="Operador",
                                selected_steps=["loja_config", "usuarios"], resume=True)
            await service.tasks[deployment.id]
            assert service.steps.get(deployment.id, "loja_config").attempts == attempts
            assert state["writes"] == 1  # Resume starts at interrupted users, not saved store data.
            await service.start(deployment.id, mode="real", confirmed=True, operator="Operador")
            await service.tasks[deployment.id]
            assert state["writes"] == 1
            assert service.steps.get(deployment.id, "loja_config").status == "skipped"
            assert service.deployments.get(deployment.id).status == "completed"
            assert service.deployments.list_audit_events(deployment.id)
        finally:
            await service.shutdown()
    asyncio.run(scenario())


@pytest.mark.parametrize("hint", ["url", "id", "conflict"])
def test_api_store_url_and_id_shortcuts_validate_cnpj(tmp_path, local_hiper, hint):
    from app.automation.hiper.errors import HiperError
    base, state = local_hiper
    async def scenario():
        manager = manager_for(tmp_path)
        service, deployment = service_for(tmp_path, manager, base)
        data = dict(deployment.data)
        if hint in {"url", "conflict"}:
            data["hiper_store_url"] = base + "/stores/one/general"
        if hint in {"id", "conflict"}:
            data["hiper_store_id"] = "wrong" if hint == "conflict" else "one"
        service.deployments.update_review(deployment.id, data)
        try:
            page = await manager.open(base)
            await page.goto(base + "/login")
            if hint == "conflict":
                with pytest.raises(HiperError):
                    await service.resolve(deployment.id)
                assert service.deployments.get(deployment.id).hiper_store_id is None
            else:
                result = await service.resolve(deployment.id)
                assert result["store"]["id"] == "one"
                assert result["store"]["cnpj"] == "12345678000195"
            assert state["writes"] == 0
        finally:
            await service.shutdown()
    asyncio.run(scenario())


def test_pause_then_resume_without_replaying_simulation(tmp_path):
    async def scenario():
        manager = manager_for(tmp_path)
        service, deployment = service_for(tmp_path, manager, "http://127.0.0.1:49999")
        await service.start(deployment.id, mode="simulation", selected_steps=["loja_config", "usuarios"])
        service.repo.pause(deployment.id)
        await service.tasks[deployment.id]
        assert service.deployments.get(deployment.id).status == "paused"
        assert service.steps.get(deployment.id, "loja_config").attempts == 0
        await service.start(deployment.id, mode="simulation", selected_steps=["loja_config", "usuarios"])
        await service.tasks[deployment.id]
        before = [step.attempts for step in service.steps.list_for_deployment(deployment.id)]
        await service.start(deployment.id, mode="simulation", selected_steps=["loja_config", "usuarios"])
        await service.tasks[deployment.id]
        assert before == [step.attempts for step in service.steps.list_for_deployment(deployment.id)]
        await service.shutdown()
    asyncio.run(scenario())


def test_ambiguous_store_manual_resolution_and_expired_session(tmp_path, local_hiper):
    base, state = local_hiper
    async def scenario():
        manager = manager_for(tmp_path)
        service, deployment = service_for(tmp_path, manager, base)
        try:
            page = await manager.open(base)
            await page.goto(base + "/login")
            state["duplicate"] = True
            with pytest.raises(HiperStoreAmbiguous):
                await service.resolve(deployment.id)
            assert not service.deployments.get(deployment.id).store_verified_at
            await service.resolve(deployment.id, selected_id="two")
            assert service.deployments.get(deployment.id).hiper_store_id == "two"
            state["authenticated"] = False
            await service.start(deployment.id, mode="real", confirmed=True, operator="Operador")
            await service.tasks[deployment.id]
            assert service.deployments.get(deployment.id).status == "awaiting_auth"
            assert state["writes"] == 0
        finally:
            await service.shutdown()
    asyncio.run(scenario())
