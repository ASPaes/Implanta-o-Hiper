"""The fixed card destinations and their shared deployment configuration."""

from typing import Any


CARD_BRANDS = (
    ("american_express", "American Express"),
    ("aura", "Aura"),
    ("elo", "Elo"),
    ("hipercard", "Hipercard"),
    ("mastercard", "Mastercard"),
    ("sorocred", "Sorocred"),
    ("visa", "Visa"),
)
CARD_ENTRIES = tuple(
    (code, name, modality)
    for code, name in CARD_BRANDS
    for modality in ("credito", "debito")
) + (("voucher", "Voucher", None),)


def card_brand_targets(data: dict[str, Any]) -> list[dict[str, Any]]:
    settings = data.get("bandeiras_cartao") or {}
    bank = data.get("instituicao_financeira") or {}
    return [
        {
            "codigo": code,
            "bandeira": name,
            "modalidade": modality,
            "credenciadora": settings.get("credenciadora", ""),
            "cliente_fornecedor": bank.get("bank_name", ""),
            "cnpj_banco": bank.get("cnpj_banco", ""),
        }
        for code, name, modality in CARD_ENTRIES
    ]
