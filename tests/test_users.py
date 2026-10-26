from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

from app.persistence.repositories import DeploymentRepository, StepRepository
from app.services.validation import validate_sections
from test_ui import review_payload


def users_payload(count):
    payload = MultiDict(review_payload())
    for field in ("nome", "usuario", "perfil"):
        payload.poplist(f"usuarios.{field}")
    for index in range(count):
        payload.add("usuarios.nome", f"Pessoa {index + 1}")
        payload.add("usuarios.usuario", f"pessoa.{index + 1}")
        payload.add("usuarios.perfil", "caixa" if index else "administrador")
    return payload


def prepare_users(app, client, count=10):
    client.post("/deployments/import", data={"contract_id": "1042"})
    repository = DeploymentRepository(app.config["DATABASE"])
    deployment = repository.list_all()[0]
    response = client.post(f"/deployments/{deployment.id}/review", data=users_payload(count))
    assert response.status_code == 302
    return repository, repository.get(deployment.id)


def test_ten_users_persist_and_execute_with_individual_passwords(app, client, monkeypatch, caplog):
    repository, deployment = prepare_users(app, client)
    assert len(deployment.data["usuarios"]) == 10
    review = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert review.count('data-user-block>') == 11  # Ten blocks and one inert template.
    assert review.count('id="add-user"') == 1
    execute = client.get(f"/deployments/{deployment.id}/execute").get_data(as_text=True)
    assert execute.count('name="usuarios.senha"') == 10
    calls = []

    def record_user(data, password, dry_run):
        calls.append((data["usuarios"], password, dry_run))
        return "dry-run://usuarios/simulado-confirmado"

    monkeypatch.setattr("app.services.orchestrator.configure_usuario", record_user)
    payload = MultiDict({
        "hiper_account": "Loja", "approved_by": "Operador", "account_confirmed": "yes",
    })
    passwords = [f"secret-for-person-{index + 1}" for index in range(10)]
    payload.setlist("usuarios.senha", passwords)
    response = client.post(f"/deployments/{deployment.id}/execute", data=payload, follow_redirects=True)
    assert repository.get(deployment.id).status == "homologacao_concluida"
    assert calls == [(user, password, True) for user, password in zip(deployment.data["usuarios"], passwords)]
    for password in passwords:
        assert password not in response.get_data(as_text=True)
        assert password not in caplog.text
        assert password.encode() not in Path(app.config["DATABASE"]).read_bytes()


@pytest.mark.parametrize("passwords", [["first"], ["first", ""], ["first", "second", "extra"]])
def test_each_user_requires_exactly_one_password_before_execution(app, client, passwords):
    repository, deployment = prepare_users(app, client, count=2)
    payload = MultiDict({
        "hiper_account": "Loja", "approved_by": "Operador", "account_confirmed": "yes",
    })
    payload.setlist("usuarios.senha", passwords)
    response = client.post(f"/deployments/{deployment.id}/execute", data=payload)
    assert "Informe a senha do usuário em cada bloco" in response.get_data(as_text=True)
    assert repository.list_audit_events(deployment.id) == []
    assert all(step.attempts == 0 for step in StepRepository(app.config["DATABASE"]).list_for_deployment(deployment.id))


def test_invalid_additional_user_keeps_all_blocks_and_values(app, client):
    repository, deployment = prepare_users(app, client, count=2)
    payload = users_payload(3)
    payload.setlist("usuarios.perfil", ["administrador", "suporte", "caixa"])
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Perfil inválido" in page
    for index in range(3):
        assert f'value="pessoa.{index + 1}"' in page
    assert len(repository.get(deployment.id).data["usuarios"]) == 2


def test_additional_user_validation_rejects_duplicates_and_missing_fields():
    errors = validate_sections({"usuarios": [
        {"nome": "Primeiro", "usuario": "caixa", "perfil": "caixa"},
        {"nome": "", "usuario": "CAIXA", "perfil": "suporte"},
    ]}, ("usuarios",))
    assert errors == {
        "usuarios.1.nome": "Campo obrigatório",
        "usuarios.1.usuario": "Usuário já informado",
        "usuarios.1.perfil": "Perfil inválido",
    }


def test_removed_users_are_no_longer_saved_or_asked_for_passwords(app, client):
    repository, deployment = prepare_users(app, client, count=4)
    response = client.post(f"/deployments/{deployment.id}/review", data=users_payload(3))
    assert response.status_code == 302
    assert len(repository.get(deployment.id).data["usuarios"]) == 3
    page = client.get(f"/deployments/{deployment.id}/execute").get_data(as_text=True)
    assert page.count('name="usuarios.senha"') == 3
    assert "pessoa.4" not in page
