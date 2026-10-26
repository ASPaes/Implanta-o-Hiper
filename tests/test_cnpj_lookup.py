import httpx
import pytest

from app.services.cnpj_lookup import normalize_cnpj


def test_cnpj_route_normalizes_and_returns_form_fields(client, monkeypatch):
    def fake_get(url, *, headers, timeout):
        assert url == "https://brasilapi.com.br/api/cnpj/v1/19131243000197"
        assert headers == {"Accept": "application/json"}
        assert timeout == 8
        return httpx.Response(200, json={
            "razao_social": "Empresa Exemplo Ltda",
            "nome_fantasia": "Exemplo",
            "logradouro": "Avenida Central",
            "bairro": "Centro",
            "municipio": "São Paulo",
            "uf": "SP",
            "cep": "01001000",
            "numero": "200",
            "qsa": [{"nome_socio": "Não enviar ao navegador"}],
        })

    monkeypatch.setattr(httpx, "get", fake_get)
    response = client.get("/api/cnpj?cnpj=19.131.243/0001-97")
    assert response.status_code == 200
    assert response.json == {
        "razao_social": "Empresa Exemplo Ltda",
        "nome_fantasia": "Exemplo",
        "logradouro": "Avenida Central",
        "bairro": "Centro",
        "municipio": "São Paulo",
        "uf": "SP",
        "cep": "01001000",
        "numero": "200",
    }


@pytest.mark.parametrize("value", ["", "123", "12.345.678/0001-999", "abc"])
def test_cnpj_route_rejects_invalid_length_without_external_call(client, monkeypatch, value):
    def unexpected_get(*args, **kwargs):
        pytest.fail("BrasilAPI não deve ser consultada com CNPJ inválido")

    monkeypatch.setattr(httpx, "get", unexpected_get)
    response = client.get("/api/cnpj", query_string={"cnpj": value})
    assert response.status_code == 400
    assert "14 dígitos" in response.json["error"]


def test_cnpj_normalization_keeps_only_ascii_digits():
    assert normalize_cnpj("19.131.243/0001-97") == "19131243000197"


@pytest.mark.parametrize("upstream_status,local_status,message", [
    (400, 400, "inválido"),
    (404, 404, "não encontrado"),
    (429, 502, "indisponível"),
    (500, 502, "indisponível"),
])
def test_cnpj_route_handles_upstream_statuses(
    client, monkeypatch, upstream_status, local_status, message,
):
    monkeypatch.setattr(
        httpx, "get", lambda *args, **kwargs: httpx.Response(upstream_status)
    )
    response = client.get("/api/cnpj?cnpj=19131243000197")
    assert response.status_code == local_status
    assert message in response.json["error"]


@pytest.mark.parametrize("failure,local_status,message", [
    (httpx.TimeoutException, 504, "demorou"),
    (httpx.ConnectError, 502, "Não foi possível"),
])
def test_cnpj_route_handles_network_failures(client, monkeypatch, failure, local_status, message):
    def unavailable(*args, **kwargs):
        raise failure("Detalhe interno não deve aparecer")

    monkeypatch.setattr(httpx, "get", unavailable)
    response = client.get("/api/cnpj?cnpj=19131243000197")
    assert response.status_code == local_status
    assert message in response.json["error"]
    assert "Detalhe interno" not in response.json["error"]


def test_cnpj_route_handles_invalid_json(client, monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda *args, **kwargs: httpx.Response(200, text="not json")
    )
    response = client.get("/api/cnpj?cnpj=19131243000197")
    assert response.status_code == 502
    assert "dados inválidos" in response.json["error"]


def test_review_contains_cnpj_lookup_fields_and_feedback(client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    from app.persistence.repositories import DeploymentRepository

    deployment = DeploymentRepository(client.application.config["DATABASE"]).list_all()[0]
    html = client.get(f"/deployments/{deployment.id}/review").get_data(as_text=True)
    for field in ("logradouro", "bairro", "municipio", "uf"):
        assert f'name="company.{field}"' in html
    assert 'data-lookup-url="/api/cnpj"' in html
    assert html.count('>Consultar CNPJ</button>') == 2
    assert 'data-cnpj-target="bank"' in html
    assert 'id="bank-cnpj-lookup-status"' in html
    assert 'id="cnpj-lookup-status"' in html
    assert '/static/review.js' in html
