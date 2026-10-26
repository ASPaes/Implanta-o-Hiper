"""Validation rules from the Phase 1 brief."""

import re
from typing import Any

from app.services.users import user_entries, user_error_key


FIXED_PRODUCT = {
    "nome": "Produto padrão",
    "ncm": "2022.10.00",
    "codigo_interno": "1",
    "unidade_principal": "UN - Unidade",
}
USER_PROFILES = ("administrador", "gerente", "caixa")


REQUIRED_FIELDS = {
    "company": ("legal_name", "trade_name", "cnpj", "postal_code"),
    "cliente_padrao": ("nome", "cpf", "cep"),
    "instituicao_financeira": ("bank_name", "cnpj_banco"),
    "produto_ncm": tuple(FIXED_PRODUCT),
    "contador": ("cnpj_contabilidade",),
    "bandeiras_cartao": ("credenciadora",),
    "usuarios": ("nome", "usuario", "perfil"),
}

STEP_SECTIONS = {
    "cliente_padrao": ("cliente_padrao",),
    "instituicao_financeira": ("instituicao_financeira",),
    "produto_ncm": ("produto_ncm",),
    "contador": ("contador",),
    "loja_config": ("company",),
    "config_vendas": ("cliente_padrao", "instituicao_financeira", "bandeiras_cartao"),
    "usuarios": ("usuarios",),
}


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def validate_sections(
    data: dict[str, Any], sections: tuple[str, ...] | None = None
) -> dict[str, str]:
    errors: dict[str, str] = {}
    selected = sections or tuple(REQUIRED_FIELDS)
    for section in selected:
        if section == "usuarios":
            continue
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            errors[section] = "Seção inválida"
            continue
        for field in REQUIRED_FIELDS.get(section, ()):
            if not str(section_data.get(field, "")).strip():
                errors[f"{section}.{field}"] = "Campo obrigatório"

    length_rules = {
        "company.cnpj": (14, "CNPJ deve ter 14 dígitos"),
        "cliente_padrao.cpf": (11, "CPF deve ter 11 dígitos"),
        "company.postal_code": (8, "CEP deve ter 8 dígitos"),
        "cliente_padrao.cep": (8, "CEP deve ter 8 dígitos"),
        "instituicao_financeira.cnpj_banco": (14, "CNPJ deve ter 14 dígitos"),
        "instituicao_financeira.cep": (8, "CEP deve ter 8 dígitos"),
        "contador.cnpj_contabilidade": (14, "CNPJ deve ter 14 dígitos"),
    }
    for path, (length, message) in length_rules.items():
        section, field = path.split(".")
        if section not in selected:
            continue
        value = data.get(section, {}).get(field, "")
        if value and len(digits(value)) != length:
            errors[path] = message
    ncm = data.get("produto_ncm", {}).get("ncm", "")
    if "produto_ncm" in selected and ncm and len(digits(ncm)) != 8:
        errors["produto_ncm.ncm"] = "NCM deve ter 8 dígitos"
    if "produto_ncm" in selected:
        product = data.get("produto_ncm", {})
        for field, expected in FIXED_PRODUCT.items():
            if field == "ncm":
                continue  # Fiscal classification belongs to the contract/accountant.
            if product.get(field) != expected:
                errors.setdefault(f"produto_ncm.{field}", "Valor fixo inválido")
    if "usuarios" in selected:
        raw_users = data.get("usuarios", {})
        if not isinstance(raw_users, (dict, list)):
            errors["usuarios"] = "Seção inválida"
            return errors
        seen_logins = set()
        for index, user in enumerate(user_entries(data)):
            if not isinstance(user, dict):
                errors[user_error_key(index, "nome")] = "Usuário inválido"
                continue
            for field in REQUIRED_FIELDS["usuarios"]:
                if not str(user.get(field, "")).strip():
                    errors[user_error_key(index, field)] = "Campo obrigatório"
            profile = user.get("perfil", "")
            if profile and profile not in USER_PROFILES:
                errors[user_error_key(index, "perfil")] = "Perfil inválido"
            login = str(user.get("usuario", "")).strip().casefold()
            if login and login in seen_logins:
                errors[user_error_key(index, "usuario")] = "Usuário já informado"
            seen_logins.add(login)
    return errors


def validate_for_step(data: dict[str, Any], step_key: str) -> dict[str, str]:
    return validate_sections(data, STEP_SECTIONS[step_key])
