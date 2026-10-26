import json

import pytest
import httpx

from app.services.contract_adapter import (
    ApiContractAdapter, ContractApiError, ContractAuthError,
    ContractNotFoundError, ContractUnavailableError, FixtureContractAdapter,
)


def test_fetches_local_contract(tmp_path):
    (tmp_path / "abc-1.json").write_text(
        json.dumps({"company": {"legal_name": "Teste"}}), encoding="utf-8"
    )
    contract = FixtureContractAdapter(tmp_path).fetch("abc-1")
    assert contract["data"]["company"]["legal_name"] == "Teste"
    assert contract["secrets"]["csc"] is None


@pytest.mark.parametrize("contract_id", ["missing", "../secret", "a/b"])
def test_rejects_missing_or_unsafe_contract_ids(tmp_path, contract_id):
    with pytest.raises(ContractNotFoundError):
        FixtureContractAdapter(tmp_path).fetch(contract_id)


@pytest.mark.parametrize("status,error", [
    (401, ContractAuthError), (404, ContractNotFoundError),
    (500, ContractApiError),
])
def test_api_errors_are_operator_friendly(monkeypatch, status, error):
    def fake_get(url, *, headers, timeout):
        assert url == "https://contratos.example/api/contratos/1042"
        assert headers == {"Authorization": "Bearer fake-token"}
        assert timeout == 10
        return httpx.Response(status)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(error) as caught:
        ApiContractAdapter("https://contratos.example", "fake-token").fetch("1042")
    assert "fake-token" not in str(caught.value)


@pytest.mark.parametrize("failure", [httpx.TimeoutException, httpx.ConnectError])
def test_api_timeout_and_connection_errors(monkeypatch, failure):
    def fake_get(*args, **kwargs):
        raise failure("private details")

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(ContractUnavailableError) as caught:
        ApiContractAdapter("https://contratos.example", "fake-token").fetch("1042")
    assert "private details" not in str(caught.value)


def test_api_success_splits_secrets(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(200, json={
            "company": {"legal_name": "Empresa"},
            "note": "CSC: secret-csc",
            "fiscal": {"csc": "secret-csc", "certificado_senha": "secret-pass",
                       "certificado_arquivo_ref": "/download/1", "tax_regime": "Simples"},
        })

    monkeypatch.setattr(httpx, "get", fake_get)
    contract = ApiContractAdapter("https://contratos.example", "fake-token").fetch("1042")
    assert contract["secrets"]["csc"] == "secret-csc"
    assert contract["secrets"]["certificado_senha"] == "secret-pass"
    assert contract["secrets"]["certificado_arquivo_ref"] == "/download/1"
    assert contract["data"]["fiscal"] == {"tax_regime": "Simples"}
    assert contract["data"]["note"] == "CSC: [REDACTED]"
