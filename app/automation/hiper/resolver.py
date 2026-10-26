"""Pure tenant/store identity rules, independent of the browser."""

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from app.automation.hiper.errors import (
    HiperError, HiperStoreAmbiguous, HiperStoreIdentityMismatch,
    HiperStoreNotFound, HiperTenantNotResolved,
)


def normalize_cnpj(value: str) -> str:
    text = str(value or "").strip()
    if re.search(r"[^0-9.\-/\s]", text):
        raise HiperError("CNPJ deve conter apenas os 14 dígitos e sua pontuação.")
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) != 14:
        raise HiperError("CNPJ deve conter 14 dígitos.")
    return digits


class HiperTenantResolver:
    def __init__(self, allow_local: bool = False):
        self.allow_local = allow_local

    def origin(self, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise HiperTenantNotResolved("Domínio Hiper não informado.")
        if "://" not in value:
            value = "https://" + (value if "." in value else value + ".hiper.com.br")
        try:
            parts = urlsplit(value)
            host = (parts.hostname or "").lower()
            port = parts.port
        except ValueError:
            raise HiperTenantNotResolved("URL Hiper inválida.") from None
        if parts.username or parts.password or parts.query or parts.fragment:
            raise HiperTenantNotResolved("URL Hiper não pode conter credenciais, query ou fragmento.")
        if self.allow_local and host in {"127.0.0.1", "localhost"} and parts.scheme == "http":
            return f"http://{host}" + (f":{port}" if port else "")
        if (parts.scheme != "https" or port not in {None, 443}
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.hiper\.com\.br", host)):
            raise HiperTenantNotResolved("Informe um subdomínio HTTPS válido de hiper.com.br.")
        return f"https://{host}"

    def resolve(self, data: dict, override: str = "", default: str = "") -> str:
        hints = [data.get(key) for key in ("hiper_store_url", "hiper_base_url", "hiper_domain")]
        hints = [str(value) for value in hints if value]
        origins = {self.origin(value) for value in hints}
        if override:
            origins.add(self.origin(override))
        if len(origins) > 1:
            raise HiperTenantNotResolved("Domínios conflitantes entre contrato e operador.")
        if origins:
            return origins.pop()
        return self.origin(default)

    def assert_session(self, current_url: str, expected: str) -> None:
        # Auth URLs may have query strings; origin comparison never trusts those.
        parts = urlsplit(current_url)
        clean = f"{parts.scheme}://{parts.netloc}"
        if self.origin(clean) != expected:
            raise HiperTenantNotResolved("A sessão está fora do domínio esperado.")

    def validate_url(self, url: str, base: str) -> str:
        if self.origin(url) != base:
            raise HiperTenantNotResolved("A rota da filial aponta para outro domínio.")
        if ".." in urlsplit(url).path or "\\" in url:
            raise HiperTenantNotResolved("Rota da filial inválida.")
        return url


@dataclass(frozen=True)
class HiperStore:
    id: str
    name: str
    cnpj: str
    url: str
    method: str = "cnpj"

    def public(self) -> dict:
        return asdict(self)


def verify_identity(expected: str, actual: str) -> None:
    if normalize_cnpj(expected) != normalize_cnpj(actual):
        raise HiperStoreIdentityMismatch("CNPJ do contrato diverge do CNPJ da filial no Hiper.")


class HiperStoreResolver:
    def choose(self, stores: list[HiperStore], cnpj: str, *, selected_id: str = "",
               mapped_id: str = "", company_name: str = "") -> HiperStore:
        expected = normalize_cnpj(cnpj)
        if selected_id:
            selected = [store for store in stores if store.id == selected_id]
            if len(selected) != 1:
                raise HiperStoreNotFound("ID selecionado não identifica uma filial única.")
            verify_identity(expected, selected[0].cnpj)
            return HiperStore(**{**selected[0].public(), "method": "manual_cnpj"})
        matches = [store for store in stores if normalize_cnpj(store.cnpj) == expected]
        if len(matches) > 1:
            raise HiperStoreAmbiguous("Mais de uma filial possui o CNPJ do contrato.",
                                      candidates=[store.public() for store in matches])
        if len(matches) == 1:
            return matches[0]
        # ID/name are diagnostic fallbacks only; identity still MUST match.
        fallback = [s for s in stores if mapped_id and s.id == mapped_id]
        if not fallback and company_name:
            normalized = " ".join(company_name.casefold().split())
            fallback = [s for s in stores if " ".join(s.name.casefold().split()) == normalized]
        if fallback:
            if len(fallback) > 1:
                raise HiperStoreAmbiguous("Nome/ID não identifica filial única.",
                                          candidates=[s.public() for s in fallback])
            verify_identity(expected, fallback[0].cnpj)
        raise HiperStoreNotFound("Nenhuma filial disponível corresponde ao CNPJ do contrato.")
