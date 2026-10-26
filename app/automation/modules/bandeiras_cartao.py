"""Card-brand boundary; real UI selectors must be captured before use."""

from typing import Any

from app.automation.base import require_captured_selectors


def configure_bandeira_cartao(target: dict[str, Any], dry_run: bool = True) -> str:
    if not target.get("credenciadora") or not target.get("cliente_fornecedor"):
        raise ValueError("Informe a credenciadora e o banco para configurar as bandeiras.")
    if dry_run:
        modality = target["modalidade"] or "unico"
        return f"dry-run://cartao/{target['codigo']}/{modality}"
    # After Codegen: find exactly one brand + modality, open its edit control,
    # compare saved values, select the acquirer and bank, save and reread.
    # Missing/ambiguous rows must stop execution with the brand identified.
    require_captured_selectors("bandeiras_cartao")
