import json
import logging
import sqlite3
from pathlib import Path

import httpx
import pytest

from app import create_app
from app.persistence.repositories import DeploymentRepository, StepRepository


def review_payload():
    return {
        "company.legal_name": "Empresa Teste Ltda",
        "company.trade_name": "Empresa Teste",
        "company.apelido": "Teste",
        "company.cnpj": "12345678000195",
        "company.postal_code": "88000000",
        "company.logradouro": "Rua Teste",
        "company.bairro": "Centro",
        "company.municipio": "Florianópolis",
        "company.uf": "SC",
        "company.inscricao_estadual": "123456789",
        "cliente_padrao.nome": "Consumidor Final",
        "cliente_padrao.cpf": "12345678909",
        "cliente_padrao.cep": "88000000",
        "cliente_padrao.numero": "100",
        "instituicao_financeira.bank_name": "Banco Teste",
        "instituicao_financeira.nome_fantasia": "Banco Teste",
        "instituicao_financeira.cnpj_banco": "11222333000144",
        "instituicao_financeira.cep": "88000000",
        "instituicao_financeira.numero": "200",
        "produto_ncm.nome": "Produto padrão",
        "produto_ncm.ncm": "2022.10.00",
        "produto_ncm.codigo_interno": "1",
        "produto_ncm.unidade_principal": "UN - Unidade",
        "contador.cnpj_contabilidade": "98765432000110",
        "fiscal.tax_regime": "Simples Nacional",
        "fiscal.csosn": "102",
        "fiscal.icms_rate": "0",
        "fiscal.conta_bancaria": "Conta Teste",
        "fiscal.caixas.numero_caixa": "2",
        "fiscal.caixas.serie_fiscal": "3",
        "bandeiras_cartao.credenciadora": "Credenciadora Teste",
        "usuarios.nome": "Cliente Piloto",
        "usuarios.usuario": "cliente.piloto",
        "usuarios.perfil": "administrador",
    }


def test_complete_dry_run_web_flow(app, client):
    response = client.post("/deployments/import", data={"contract_id": "1042"})
    assert response.status_code == 302
    deployment = DeploymentRepository(app.config["DATABASE"]).list_all()[0]

    response = client.post(f"/deployments/{deployment.id}/review", data=review_payload())
    assert response.status_code == 302
    assert "/execute" in response.location

    response = client.post(f"/deployments/{deployment.id}/execute", data={
        "hiper_account": "Loja Correta",
        "approved_by": "Maria",
        "account_confirmed": "yes",
        "usuarios.senha": "senha-temporaria-teste",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert "homologacao concluida" in response.get_data(as_text=True)
    assert all(
        step.status == "concluida"
        for step in StepRepository(app.config["DATABASE"]).list_for_deployment(deployment.id)
    )


def test_new_fields_required_marker_and_fixed_product(app, client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    deployment = DeploymentRepository(app.config["DATABASE"]).list_all()[0]
    review = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert 'name="cliente_padrao.numero"' in review
    assert 'name="instituicao_financeira.nome_fantasia"' in review
    assert 'name="instituicao_financeira.cep"' in review
    assert 'name="instituicao_financeira.numero"' in review
    assert 'class="required-marker"' in review
    assert 'name="usuarios.perfil"' in review
    for profile in ("administrador", "gerente", "caixa"):
        assert f'value="{profile}"' in review

    payload = review_payload()
    payload["produto_ncm.ncm"] = "00000000"
    payload["produto_ncm.nome"] = "Outro produto"
    payload["produto_ncm.codigo_interno"] = "99"
    payload["produto_ncm.unidade_principal"] = "KG"
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    assert response.status_code == 302
    stored = DeploymentRepository(app.config["DATABASE"]).get(deployment.id).data
    assert stored["produto_ncm"] == {
        "nome": "Produto padrão", "ncm": "2022.10.00",
        "codigo_interno": "1", "unidade_principal": "UN - Unidade",
    }
    assert stored["cliente_padrao"]["numero"] == "100"
    assert stored["company"]["logradouro"] == "Rua Teste"
    assert stored["company"]["bairro"] == "Centro"
    assert stored["company"]["municipio"] == "Florianópolis"
    assert stored["company"]["uf"] == "SC"
    assert stored["instituicao_financeira"]["cnpj_banco"] == "11222333000144"
    assert stored["usuarios"][0]["perfil"] == "administrador"


def test_fiscal_fields_switches_and_derived_values(app, client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    deployment = DeploymentRepository(app.config["DATABASE"]).list_all()[0]
    review = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert "Apelido (opcional)" in review
    assert "Inscrição estadual (IE)" in review
    assert "Isenta de IE" in review
    assert "Habilitar Busca Automática da NF-e" in review
    assert "Caixas" in review
    assert "Série fiscal" in review
    assert "Recebimentos" in review
    assert "Certificado digital" in review
    assert "Senha (certificado digital)" in review
    assert "CSC" in review
    assert review.count('role="switch"') == 3

    payload = review_payload()
    payload["company.isenta_ie"] = "yes"
    payload["fiscal.busca_automatica_nfe"] = "yes"
    payload["instituicao_financeira.bank_name"] = "Banco Santander"
    payload["fiscal.cliente_fornecedor"] = "Banco incorreto"
    payload["fiscal.confissao_divida"] = "Texto alterado"
    payload["fiscal.recebimentos.numero_vias"] = "99"
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    assert response.status_code == 302
    data = DeploymentRepository(app.config["DATABASE"]).get(deployment.id).data
    assert data["company"]["apelido"] == "Teste"
    assert data["company"]["isenta_ie"] is True
    assert data["company"]["inscricao_estadual"] == ""
    assert data["fiscal"]["busca_automatica_nfe"] is True
    assert data["fiscal"]["cliente_fornecedor"] == "Banco Santander"
    assert data["fiscal"]["conta_bancaria"] == "Conta Teste"
    assert data["fiscal"]["confissao_divida"] == (
        "Tenho ciência da divida no valor de R$ [ValorDocumento]"
    )
    assert data["fiscal"]["caixas"] == [{"numero_caixa": "2", "serie_fiscal": "3"}]
    assert data["fiscal"]["recebimentos"] == {"numero_vias": 1}


def test_fiscal_secret_fields_show_presence_without_values(tmp_path):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    source = json.loads((Path(__file__).parents[1] /
                         "fixtures" / "contracts" / "1042.json").read_text(encoding="utf-8"))
    source["fiscal"].update({
        "csc": "csc-secret-test", "certificado_senha": "pfx-pass-test",
        "certificado_digital": "certificate-binary-test",
    })
    (fixture_dir / "1042.json").write_text(json.dumps(source), encoding="utf-8")
    app = create_app({
        "TESTING": True, "SECRET_KEY": "test", "DATABASE": str(tmp_path / "test.db"),
        "FIXTURES_PATH": str(fixture_dir), "CONTRACT_SOURCE": "fixture", "DRY_RUN": True,
    })
    client = app.test_client()
    client.post("/deployments/import", data={"contract_id": "1042"})
    deployment = DeploymentRepository(app.config["DATABASE"]).list_all()[0]
    review = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert review.count("Recebido do contrato") == 3
    client.post(f"/deployments/{deployment.id}/review", data=review_payload())
    review_again = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert review_again.count("Recebido do contrato") == 3
    database_bytes = Path(app.config["DATABASE"]).read_bytes()
    for secret in ("csc-secret-test", "pfx-pass-test", "certificate-binary-test"):
        assert secret not in review
        assert secret not in review_again
        assert secret.encode() not in database_bytes


def test_user_password_is_required_before_execution(app, client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    deployment = DeploymentRepository(app.config["DATABASE"]).list_all()[0]
    client.post(f"/deployments/{deployment.id}/review", data=review_payload())
    response = client.post(f"/deployments/{deployment.id}/execute", data={
        "hiper_account": "Loja Correta", "approved_by": "Maria",
        "account_confirmed": "yes",
    }, follow_redirects=True)
    assert "Informe a senha do usuário" in response.get_data(as_text=True)
    assert not DeploymentRepository(app.config["DATABASE"]).list_audit_events(deployment.id)
    assert all(step.attempts == 0 for step in StepRepository(
        app.config["DATABASE"]
    ).list_for_deployment(deployment.id))


def test_execution_requires_explicit_account_confirmation(app, client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    deployment = DeploymentRepository(app.config["DATABASE"]).list_all()[0]
    client.post(f"/deployments/{deployment.id}/review", data=review_payload())
    response = client.post(f"/deployments/{deployment.id}/execute", data={
        "hiper_account": "Loja", "approved_by": "Maria"
    }, follow_redirects=True)
    assert "confirme explicitamente" in response.get_data(as_text=True)
    refreshed = DeploymentRepository(app.config["DATABASE"]).get(deployment.id)
    assert refreshed.status == "aguardando_confirmacao_conta"


@pytest.mark.parametrize("status,expected", [
    (401, "inválido ou expirado"),
    (404, "não encontrado"),
    (500, "erro inesperado"),
])
def test_api_errors_appear_in_ui(tmp_path, monkeypatch, status, expected):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "test", "DATABASE": str(tmp_path / "test.db"),
        "CONTRACT_SOURCE": "api", "CONTRATOS_API_URL": "https://contratos.example",
        "CONTRATOS_API_TOKEN": "fake-token",
    })
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(status))
    response = app.test_client().post(
        "/deployments/import", data={"contract_id": "1042"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert expected in response.get_data(as_text=True)
    assert not DeploymentRepository(app.config["DATABASE"]).list_all()


@pytest.mark.parametrize("failure,expected", [
    (httpx.TimeoutException, "demorou a responder"),
    (httpx.ConnectError, "Não foi possível conectar"),
])
def test_api_unavailable_appears_in_ui(tmp_path, monkeypatch, failure, expected):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "test", "DATABASE": str(tmp_path / "test.db"),
        "CONTRACT_SOURCE": "api", "CONTRATOS_API_URL": "https://contratos.example",
        "CONTRATOS_API_TOKEN": "fake-token",
    })
    def unavailable(*args, **kwargs):
        raise failure("private details")
    monkeypatch.setattr(httpx, "get", unavailable)
    response = app.test_client().post(
        "/deployments/import", data={"contract_id": "1042"}, follow_redirects=True
    )
    assert expected in response.get_data(as_text=True)
    assert "private details" not in response.get_data(as_text=True)


def test_zero_secret_leak_in_full_dry_run(tmp_path, caplog):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    source = json.loads((Path(__file__).parents[1] /
                         "fixtures" / "contracts" / "1042.json").read_text(encoding="utf-8"))
    csc = "CSC-unique-test-8792"
    password = "PFX-pass-unique-test-6471"
    source["fiscal"].update({
        "csc": csc, "certificado_senha": password,
        "certificado_arquivo_ref": "/api/certificados/1",
    })
    (fixture_dir / "1042.json").write_text(json.dumps(source), encoding="utf-8")
    app = create_app({
        "TESTING": True, "SECRET_KEY": "test", "DATABASE": str(tmp_path / "test.db"),
        "FIXTURES_PATH": str(fixture_dir), "CONTRACT_SOURCE": "fixture", "DRY_RUN": True,
    })
    client = app.test_client()
    with caplog.at_level(logging.DEBUG):
        response = client.post("/deployments/import", data={"contract_id": "1042"})
        assert response.status_code == 302
        deployment = DeploymentRepository(app.config["DATABASE"]).list_all()[0]
        client.post(f"/deployments/{deployment.id}/review", data=review_payload())
        response = client.post(f"/deployments/{deployment.id}/execute", data={
            "hiper_account": "Loja Correta", "approved_by": "Maria",
            "account_confirmed": "yes",
            "usuarios.senha": "senha-usuario-secreta-teste",
        }, follow_redirects=True)
    report = response.get_data(as_text=True)
    with sqlite3.connect(app.config["DATABASE"]) as connection:
        data_json = connection.execute(
            "SELECT data_json FROM deployments WHERE id = ?", (deployment.id,)
        ).fetchone()[0]
    for secret in (csc, password, "/api/certificados/1", "senha-usuario-secreta-teste"):
        assert secret not in data_json
        assert secret not in caplog.text
        assert secret not in report
        assert secret.encode() not in Path(app.config["DATABASE"]).read_bytes()
    assert "homologacao concluida" in report
    assert "execucao iniciada" in report
    assert "Maria" in report
