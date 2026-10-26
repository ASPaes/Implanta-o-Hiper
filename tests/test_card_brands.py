from copy import deepcopy

import pytest

from app.automation.base import SelectorsNotCapturedError
from app.automation.modules.bandeiras_cartao import configure_bandeira_cartao
from app.automation.modules.loja import configure_vendas
from app.persistence.repositories import DeploymentRepository, StepRepository
from app.services.card_brands import card_brand_targets
from app.services.orchestrator import Orchestrator, ValidationBlockedError
from app.services.validation import validate_for_step
from test_orchestrator import prepared
from test_ui import review_payload


EXPECTED_ENTRIES = {
    (name, modality)
    for name in ("American Express", "Aura", "Elo", "Hipercard", "Mastercard", "Sorocred", "Visa")
    for modality in ("credito", "debito")
} | {("Voucher", None)}


def imported(app, client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    repository = DeploymentRepository(app.config["DATABASE"])
    return repository, repository.list_all()[0]


def test_empty_acquirer_is_required_and_bank_is_derived(app, client):
    repository, deployment = imported(app, client)
    page = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert 'name="bandeiras_cartao.credenciadora" value=""' in page
    assert page.count("data-card-entry") == 15
    assert "Banco de Homologação" in page
    payload = review_payload()
    payload["bandeiras_cartao.credenciadora"] = "   "
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    assert response.status_code == 200
    assert "Campo obrigatório" in response.get_data(as_text=True)
    assert repository.get(deployment.id).status == "rascunho"
    payload["bandeiras_cartao.credenciadora"] = "  Credenciadora Escolhida  "
    payload["bandeiras_cartao.cliente_fornecedor"] = "Banco adulterado"
    payload["bandeiras_cartao.entradas"] = "apenas visa"
    payload["instituicao_financeira.bank_name"] = "Banco Selecionado"
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    assert response.status_code == 302
    data = repository.get(deployment.id).data
    assert data["bandeiras_cartao"] == {
        "credenciadora": "Credenciadora Escolhida", "cliente_fornecedor": "Banco Selecionado",
    }
    targets = card_brand_targets(data)
    assert len(targets) == 15
    assert {(target["bandeira"], target["modalidade"]) for target in targets} == EXPECTED_ENTRIES
    assert all(target["credenciadora"] == "Credenciadora Escolhida" for target in targets)
    assert all(target["cliente_fornecedor"] == "Banco Selecionado" for target in targets)
    assert all(target["cnpj_banco"] == "11222333000144" for target in targets)
    page = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert 'value="Credenciadora Escolhida"' in page
    assert 'name="bandeiras_cartao.cliente_fornecedor" value="Banco Selecionado" readonly' in page


def test_dry_run_configures_all_fifteen_destinations(app, monkeypatch):
    repository, steps, deployment_id = prepared(app)
    calls = []

    def record_target(target, dry_run):
        calls.append((target, dry_run))
        return configure_bandeira_cartao(target, dry_run)

    monkeypatch.setattr("app.automation.modules.loja.configure_bandeira_cartao", record_target)
    orchestrator = Orchestrator(repository, steps)
    orchestrator.run(deployment_id, user_password="test-password")
    assert len(calls) == 15
    assert {(target["bandeira"], target["modalidade"]) for target, _ in calls} == EXPECTED_ENTRIES
    assert all(dry_run for _, dry_run in calls)
    evidence = steps.get(deployment_id, "config_vendas").evidence_reference
    assert evidence.count("dry-run://cartao/") == 15
    assert "dry-run://cartao/voucher/unico" in evidence
    orchestrator.run(deployment_id)
    assert len(calls) == 15


def test_missing_acquirer_blocks_sales_and_resume_preserves_finished_steps(app):
    repository, steps, deployment_id = prepared(app)
    data = repository.get(deployment_id).data
    data.pop("bandeiras_cartao")
    repository.update_review(deployment_id, data)
    orchestrator = Orchestrator(repository, steps)
    with pytest.raises(ValidationBlockedError, match="bandeiras_cartao.credenciadora"):
        orchestrator.run(deployment_id, user_password="test-password")
    assert steps.get(deployment_id, "config_vendas").status == "aguardando_operador"
    assert steps.get(deployment_id, "usuarios").attempts == 0
    data["bandeiras_cartao"] = {"credenciadora": "Credenciadora Escolhida"}
    repository.update_review(deployment_id, data)
    orchestrator.run(deployment_id, user_password="test-password")
    assert repository.get(deployment_id).status == "homologacao_concluida"
    assert [step.attempts for step in steps.list_for_deployment(deployment_id)] == [1] * 7


@pytest.mark.parametrize("field", ["bank_name", "cnpj_banco"])
def test_sales_requires_the_bank_as_well_as_acquirer(app, field):
    repository, _, deployment_id = prepared(app)
    data = repository.get(deployment_id).data
    data["instituicao_financeira"][field] = ""
    assert f"instituicao_financeira.{field}" in validate_for_step(data, "config_vendas")


@pytest.mark.parametrize("change", ["acquirer", "bank_name", "bank_cnpj"])
def test_changed_card_configuration_reopens_only_sales(app, change):
    repository, steps, deployment_id = prepared(app)
    orchestrator = Orchestrator(repository, steps)
    orchestrator.run(deployment_id, user_password="test-password")
    data = deepcopy(repository.get(deployment_id).data)
    repository.update_review(deployment_id, data)
    assert steps.get(deployment_id, "config_vendas").status == "concluida"
    if change == "acquirer":
        data["bandeiras_cartao"]["credenciadora"] = "Outra Credenciadora"
    else:
        data["instituicao_financeira"]["bank_name" if change == "bank_name" else "cnpj_banco"] = (
            "Outro Banco" if change == "bank_name" else "11222333000225"
        )
    repository.update_review(deployment_id, data)
    assert steps.get(deployment_id, "config_vendas").status == "pendente"
    assert all(step.status == "concluida" for step in steps.list_for_deployment(deployment_id) if step.step_key != "config_vendas")
    orchestrator.run(deployment_id)
    assert [step.attempts for step in steps.list_for_deployment(deployment_id)] == [1, 1, 1, 1, 1, 2, 1]


def test_real_mode_stays_blocked_for_sales_and_cards(app):
    repository, _, deployment_id = prepared(app)
    data = repository.get(deployment_id).data
    with pytest.raises(SelectorsNotCapturedError, match="config_vendas"):
        configure_vendas(data, dry_run=False)
    with pytest.raises(SelectorsNotCapturedError, match="bandeiras_cartao"):
        configure_bandeira_cartao(card_brand_targets(data)[0], dry_run=False)
