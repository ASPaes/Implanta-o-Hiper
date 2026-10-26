"""CNPJ lookup through BrasilAPI, with operator-friendly failures."""

import re
from typing import Any

import httpx


BRASILAPI_CNPJ_URL = "https://brasilapi.com.br/api/cnpj/v1"


class InvalidCnpjError(ValueError):
    pass


class CnpjNotFoundError(LookupError):
    pass


class CnpjServiceError(RuntimeError):
    pass


class CnpjTimeoutError(CnpjServiceError):
    pass


def normalize_cnpj(value: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) != 14:
        raise InvalidCnpjError("Informe um CNPJ com 14 dígitos.")
    return digits


def lookup_cnpj(value: str) -> dict[str, str]:
    cnpj = normalize_cnpj(value)
    try:
        response = httpx.get(
            f"{BRASILAPI_CNPJ_URL}/{cnpj}",
            headers={"Accept": "application/json"},
            timeout=8,
        )
    except httpx.TimeoutException as error:
        raise CnpjTimeoutError("A consulta demorou a responder. Tente novamente.") from error
    except httpx.RequestError as error:
        raise CnpjServiceError("Não foi possível consultar a BrasilAPI agora.") from error

    if response.status_code == 404:
        raise CnpjNotFoundError("CNPJ não encontrado.")
    if response.status_code == 400:
        raise InvalidCnpjError("A BrasilAPI considerou este CNPJ inválido.")
    if response.status_code >= 400:
        raise CnpjServiceError("A BrasilAPI está indisponível. Tente novamente.")

    try:
        payload: Any = response.json()
    except ValueError as error:
        raise CnpjServiceError("A BrasilAPI retornou dados inválidos.") from error
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("razao_social"), str)
        or not payload["razao_social"].strip()
    ):
        raise CnpjServiceError("A BrasilAPI retornou dados incompletos.")

    fields = (
        "razao_social", "nome_fantasia", "logradouro", "bairro", "municipio", "uf",
        "cep", "numero",
    )
    return {
        field: payload[field] if isinstance(payload.get(field), str) else ""
        for field in fields
    }
