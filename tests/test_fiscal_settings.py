from pathlib import Path

from werkzeug.datastructures import MultiDict

from app import create_app
from app.persistence.repositories import DeploymentRepository
from test_ui import review_payload


def import_deployment(app, client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    repository = DeploymentRepository(app.config["DATABASE"])
    return repository, repository.list_all()[0]


def test_pix_reuses_existing_fields_and_starts_with_empty_account(app, client):
    repository, deployment = import_deployment(app, client)
    assert deployment.data["fiscal"]["conta_bancaria"] == ""
    assert deployment.data["fiscal"]["caixas"] == [{"numero_caixa": "1", "serie_fiscal": "1"}]
    page = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    for field in ("cliente_fornecedor", "conta_bancaria", "confissao_divida"):
        assert page.count(f'name="fiscal.{field}"') == 1
    assert "Configurações de Pix" in page
    assert "Configurações de NFC-e" in page
    assert 'name="fiscal.csosn"' in page
    assert 'name="fiscal.nfce.token"' in page
    assert "Imprimir nome fantasia da loja no pedido de venda e no orçamento" in page

    payload = review_payload()
    payload["fiscal.imprimir_nome_fantasia"] = "yes"
    payload["fiscal.conta_bancaria"] = "Conta caixa - Empresa Teste"
    payload["fiscal.confissao_divida"] = "Alterada"
    payload["fiscal.cliente_fornecedor"] = "Banco incorreto"
    client.post(f"/deployments/{deployment.id}/review", data=payload)
    fiscal = repository.get(deployment.id).data["fiscal"]
    assert fiscal["conta_bancaria"] == "Conta caixa - Empresa Teste"
    assert fiscal["cliente_fornecedor"] == "Banco Teste"
    assert fiscal["confissao_divida"] == "Tenho ciência da divida no valor de R$ [ValorDocumento]"
    assert fiscal["imprimir_nome_fantasia"] is True
    page = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert 'name="fiscal.imprimir_nome_fantasia" value="yes" role="switch" checked' in page
    payload.pop("fiscal.imprimir_nome_fantasia")
    payload["fiscal.conta_bancaria"] = ""
    client.post(f"/deployments/{deployment.id}/review", data=payload)
    fiscal = repository.get(deployment.id).data["fiscal"]
    assert fiscal["imprimir_nome_fantasia"] is False
    assert fiscal["conta_bancaria"] == ""


def test_multiple_caixas_keep_order_and_survive_invalid_review(app, client):
    repository, deployment = import_deployment(app, client)
    payload = MultiDict(review_payload())
    payload.setlist("fiscal.caixas.numero_caixa", ["1", "3", "4"])
    payload.setlist("fiscal.caixas.serie_fiscal", ["01", "03", "04"])
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    assert response.status_code == 302
    fiscal = repository.get(deployment.id).data["fiscal"]
    assert fiscal["caixas"] == [
        {"numero_caixa": "1", "serie_fiscal": "01"},
        {"numero_caixa": "3", "serie_fiscal": "03"},
        {"numero_caixa": "4", "serie_fiscal": "04"},
    ]
    payload["company.legal_name"] = ""
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert page.count('data-caixa-block>') == 4  # Three visible blocks and an inert template.
    assert 'value="03"' in page
    assert 'value="04"' in page


def test_nfce_identifier_persists_and_token_stays_in_memory(app, client, caplog):
    repository, deployment = import_deployment(app, client)
    payload = review_payload()
    token = "private-csc-test-89473"
    payload["fiscal.nfce.numero_identificacao"] = "000001"
    payload["fiscal.nfce.token"] = token
    payload["company.legal_name"] = ""
    response = client.post(f"/deployments/{deployment.id}/review", data=payload)
    assert "Token disponível nesta sessão" in response.get_data(as_text=True)
    assert token not in response.get_data(as_text=True)
    payload["company.legal_name"] = "Empresa"
    payload["fiscal.nfce.token"] = ""
    client.post(f"/deployments/{deployment.id}/review", data=payload)
    assert repository.get(deployment.id).data["fiscal"]["nfce"] == {"numero_identificacao": "000001"}
    assert app.extensions["nfce_tokens"][deployment.id] == token
    assert token.encode() not in Path(app.config["DATABASE"]).read_bytes()
    assert token not in caplog.text
    page = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    assert 'value="000001"' in page
    assert "Token disponível nesta sessão" in page
    assert token not in page
    restarted = create_app(dict(app.config))
    assert restarted.extensions["nfce_tokens"] == {}
