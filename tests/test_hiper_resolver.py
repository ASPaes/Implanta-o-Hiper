import pytest

from app.automation.hiper.errors import (
    HiperError, HiperStoreAmbiguous, HiperStoreIdentityMismatch,
    HiperStoreNotFound, HiperTenantNotResolved,
)
from app.automation.hiper.resolver import HiperStore, HiperStoreResolver, HiperTenantResolver, normalize_cnpj
from app.services.contract_adapter import ApiContractAdapter, normalize
from app.security.redaction import redact_secrets, sanitize_text


@pytest.mark.parametrize("value", ["12.345.678/0001-95", "12345678000195"])
def test_cnpj_normalization(value):
    assert normalize_cnpj(value) == "12345678000195"


@pytest.mark.parametrize("value", ["123", "", "abc12345678000195"])
def test_invalid_cnpj(value):
    with pytest.raises(HiperError):
        normalize_cnpj(value)


@pytest.mark.parametrize("value", ["cliente", "cliente.hiper.com.br", "https://cliente.hiper.com.br/configuracoes/loja/xyz/dados-gerais"])
def test_tenant_origin(value):
    assert HiperTenantResolver().origin(value) == "https://cliente.hiper.com.br"


@pytest.mark.parametrize("value", ["http://cliente.hiper.com.br", "https://hiper.com.br.evil.test",
    "https://evil.test", "https://user:pass@cliente.hiper.com.br", "http://127.0.0.1:4000",
    "https://cliente.hiper.com.br?token=abc", "https://cliente.hiper.com.br:99999"])
def test_unsafe_tenants_rejected(value):
    with pytest.raises(HiperTenantNotResolved):
        HiperTenantResolver().origin(value)


def test_conflicting_hints_and_session():
    resolver = HiperTenantResolver()
    with pytest.raises(HiperTenantNotResolved):
        resolver.resolve({"hiper_domain": "one", "hiper_base_url": "https://two.hiper.com.br"})
    with pytest.raises(HiperTenantNotResolved):
        resolver.assert_session("https://two.hiper.com.br", "https://one.hiper.com.br")
    assert resolver.resolve({"hiper_domain": None}, "one") == "https://one.hiper.com.br"


def stores():
    return [HiperStore("one", "Empresa", "12.345.678/0001-95", "https://one.hiper.com.br/store/one"),
            HiperStore("two", "Outra", "11222333000144", "https://one.hiper.com.br/store/two")]


def test_store_exact_cnpj_beats_mapping():
    assert HiperStoreResolver().choose(stores(), "12345678000195", mapped_id="two").id == "one"


def test_not_found_and_mismatch():
    with pytest.raises(HiperStoreNotFound):
        HiperStoreResolver().choose(stores(), "99999999000199")
    with pytest.raises(HiperStoreIdentityMismatch):
        HiperStoreResolver().choose(stores(), "99999999000199", mapped_id="one")
    with pytest.raises(HiperStoreIdentityMismatch):
        HiperStoreResolver().choose(stores(), "12345678000195", selected_id="two")


def test_duplicate_store_requires_manual_even_with_mapping():
    choices = stores() + [HiperStore("three", "Empresa 2", "12345678000195", "https://one.hiper.com.br/store/three")]
    with pytest.raises(HiperStoreAmbiguous) as error:
        HiperStoreResolver().choose(choices, "12345678000195", mapped_id="one")
    assert len(error.value.candidates) == 2
    assert HiperStoreResolver().choose(choices, "12345678000195", selected_id="three").method == "manual_cnpj"


def test_flat_and_legacy_contract_mapping():
    flat = normalize({"id": "1042", "company": "Empresa", "cnpj": "12345678000195",
        "cep": "88500000", "email": "test@example.test", "users": [{"name": "Pessoa", "role": "vendedor"}],
        "hiper_domain": "one", "hiper_store_id": None, "csc_token": "never-visible"})
    assert flat["company"]["legal_name"] == "Empresa"
    assert flat["company"]["postal_code"] == "88500000"
    assert flat["usuarios"][0]["nome"] == "Pessoa"
    assert flat["hiper_domain"] == "one"
    assert "csc_token" not in flat
    legacy = {"company": {"legal_name": "Empresa"}, "usuarios": {"nome": "Um"}}
    assert normalize(legacy) == legacy


def test_modern_contract_endpoint(monkeypatch):
    import httpx
    called = []
    def fetch(url, **kwargs):
        called.append((url, kwargs))
        return httpx.Response(200, json={"company": "Empresa"})
    monkeypatch.setattr(httpx, "get", fetch)
    ApiContractAdapter("https://contracts.example/contracts", "private", path_prefix="").fetch("1042")
    assert called[0][0] == "https://contracts.example/contracts/1042"


def test_redacts_authorization_and_cookies():
    assert "private-value" not in sanitize_text("Authorization: Bearer private-value")
    assert "private-value" not in sanitize_text("cookie=private-value")
    assert "private-value" not in str(redact_secrets({"cookies": ["private-value"], "storage_state": "private-value"}))


def test_review_preserves_api_ncm_and_never_invents_missing_value():
    from app import _prepare_data
    assert _prepare_data({"produto_ncm": {"ncm": "API-NCM"}})["produto_ncm"]["ncm"] == "API-NCM"
    assert _prepare_data({})["produto_ncm"]["ncm"] == ""
