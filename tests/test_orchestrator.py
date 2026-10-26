import pytest

from app.automation.base import SelectorsNotCapturedError
from app.automation.modules.usuarios import configure_usuario
from app.models import STEP_KEYS
from app.persistence.repositories import DeploymentRepository, StepRepository
from app.services.contract_adapter import FixtureContractAdapter
from app.services.orchestrator import Orchestrator


def prepared(app):
    deployments = DeploymentRepository(app.config["DATABASE"])
    steps = StepRepository(app.config["DATABASE"])
    data = FixtureContractAdapter(app.config["FIXTURES_PATH"]).fetch("1042")["data"]
    data["bandeiras_cartao"] = {"credenciadora": "Credenciadora Teste"}
    deployment = deployments.create("1042", data)
    deployments.update_review(deployment.id, data)
    deployments.confirm_account(deployment.id, "Loja Homologação", "Operador")
    return deployments, steps, deployment.id


def test_dry_run_completes_all_steps(app):
    deployments, steps, deployment_id = prepared(app)
    Orchestrator(deployments, steps).run(
        deployment_id, dry_run=True, user_password="senha-temporaria-teste"
    )
    assert deployments.get(deployment_id).status == "homologacao_concluida"
    results = steps.list_for_deployment(deployment_id)
    assert all(step.status == "concluida" for step in results)
    assert all(step.evidence_reference.startswith("dry-run://") for step in results)
    audit = deployments.list_audit_events(deployment_id)
    assert len(audit) == 1
    assert audit[0].actor == "Operador"
    assert audit[0].occurred_at


def test_resume_does_not_repeat_completed_steps(app):
    deployments, steps, deployment_id = prepared(app)
    orchestrator = Orchestrator(deployments, steps)
    orchestrator.run(deployment_id, dry_run=True, user_password="senha-temporaria-teste")
    orchestrator.run(deployment_id, dry_run=True)
    assert [step.attempts for step in steps.list_for_deployment(deployment_id)] == [1] * 7


def test_real_mode_is_explicitly_blocked(app):
    deployments, steps, deployment_id = prepared(app)
    with pytest.raises(SelectorsNotCapturedError):
        Orchestrator(deployments, steps).run(
            deployment_id, dry_run=False, user_password="senha-temporaria-teste"
        )
    first = steps.get(deployment_id, STEP_KEYS[0])
    assert first.status == "aguardando_operador"
    assert first.error_code == "SELECTORS_NOT_CAPTURED"
    assert deployments.get(deployment_id).status == "aguardando_intervencao"


def test_user_real_mode_is_blocked_without_captured_selectors():
    with pytest.raises(SelectorsNotCapturedError) as error:
        configure_usuario(
            {"usuarios": {"nome": "Cliente", "usuario": "cliente", "perfil": "caixa"}},
            "senha-temporaria-teste", dry_run=False,
        )
    assert "senha-temporaria-teste" not in str(error.value)
