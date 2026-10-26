"""Contract adapters. Only normalized, non-secret data may be persisted."""

import json
import re
from pathlib import Path
from typing import Any

import httpx


class ContractError(Exception):
    """An operator-facing failure while importing a contract."""


class ContractNotFoundError(ContractError):
    pass


class ContractAuthError(ContractError):
    pass


class ContractUnavailableError(ContractError):
    pass


class ContractApiError(ContractError):
    pass


_SECRET_FIELDS = {
    "csc", "certificado_senha", "certificado_arquivo_ref",
    "certificado_digital", "certificado_arquivo", "certificado_base64",
    "certificado", "certificado_pfx", "certificado_p12",
}
_SECRET_FRAGMENTS = (
    "password", "senha", "secret", "token", "api_key", "apikey", "certificado",
    "cookie", "authorization", "storage_state",
)


def _valid_contract_id(contract_id: str) -> str:
    contract_id = str(contract_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", contract_id):
        raise ContractNotFoundError("Identificador de contrato inválido.")
    return contract_id


def extract_secrets(raw: dict[str, Any]) -> dict[str, Any]:
    fiscal = raw.get("fiscal")
    fiscal = fiscal if isinstance(fiscal, dict) else {}
    return {key: fiscal.get(key) for key in _SECRET_FIELDS}


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Copy contract data while removing secret fields at any nesting level."""
    secret_values = [
        value for value in extract_secrets(raw).values()
        if isinstance(value, str) and value
    ]

    def gather(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if any(fragment in key.lower() for fragment in (*_SECRET_FRAGMENTS, "csc")):
                    if isinstance(item, str) and item:
                        secret_values.append(item)
                else:
                    gather(item)
        elif isinstance(value, list):
            for item in value:
                gather(item)
    gather(raw)

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: clean(item)
                for key, item in value.items()
                if key.lower() not in _SECRET_FIELDS
                and not any(part in key.lower() for part in _SECRET_FRAGMENTS)
                and not any(secret in key for secret in secret_values)
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            for secret in secret_values:
                value = value.replace(secret, "[REDACTED]")
        return value

    data = clean(raw)
    if isinstance(data.get("company"), str):
        data["company"] = {
            "legal_name": data["company"], "trade_name": raw.get("trade_name", ""),
            "cnpj": raw.get("cnpj", ""), "postal_code": raw.get("cep", ""),
            "email": raw.get("email", ""),
        }
    if "users" in data and "usuarios" not in data:
        users = data["users"]
        if not isinstance(users, list) or any(not isinstance(user, dict) for user in users):
            raise ContractApiError("Lista de usuários do contrato inválida.")
        data["usuarios"] = [{"nome": user.get("name", ""),
                             "usuario": user.get("username", ""),
                             "perfil": user.get("role", "")} for user in users]
    return data


def split_contract(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ContractApiError("A API de contratos retornou dados inválidos.")
    return {"data": normalize(raw), "secrets": extract_secrets(raw)}


class FixtureContractAdapter:
    def __init__(self, fixtures_path: str | Path):
        self.fixtures_path = Path(fixtures_path)

    def fetch(self, contract_id: str) -> dict[str, dict[str, Any]]:
        contract_id = _valid_contract_id(contract_id)
        path = self.fixtures_path / f"{contract_id}.json"
        if not path.is_file():
            raise ContractNotFoundError(f"Contrato '{contract_id}' não encontrado.")
        with path.open(encoding="utf-8") as fixture:
            return split_contract(json.load(fixture))


class ApiContractAdapter:
    def __init__(self, base_url: str | None, token: str | None, *, path_prefix: str = "/api/contratos"):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.path_prefix = path_prefix.rstrip("/")

    def fetch(self, contract_id: str) -> dict[str, dict[str, Any]]:
        contract_id = _valid_contract_id(contract_id)
        if not self.base_url or not self.token:
            raise ContractApiError(
                "API de contratos não configurada. Defina CONTRATOS_API_URL e "
                "CONTRATOS_API_TOKEN no ambiente."
            )
        try:
            response = httpx.get(
                f"{self.base_url}{self.path_prefix}/{contract_id}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10,
            )
        except httpx.TimeoutException as error:
            raise ContractUnavailableError(
                "A API de contratos demorou a responder. Tente novamente."
            ) from error
        except httpx.RequestError as error:
            raise ContractUnavailableError(
                "Não foi possível conectar à API de contratos. Tente novamente."
            ) from error
        if response.status_code == 401:
            raise ContractAuthError("Token da API de contratos inválido ou expirado.")
        if response.status_code == 404:
            raise ContractNotFoundError(f"Contrato '{contract_id}' não encontrado.")
        if response.status_code >= 400:
            raise ContractApiError(
                "A API de contratos retornou um erro inesperado. Tente novamente."
            )
        try:
            return split_contract(response.json())
        except ValueError as error:
            raise ContractApiError("A API de contratos retornou dados inválidos.") from error
