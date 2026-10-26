"""Customer and financial institution automation boundaries."""

from typing import Any

from app.automation.base import dry_run_result, require_captured_selectors


def configure_cliente_padrao(data: dict[str, Any], dry_run: bool = True) -> str:
    if dry_run:
        return dry_run_result("cliente_padrao", data)
    # Real flow after Codegen: find -> create/edit/skip -> fill -> save -> reread.
    require_captured_selectors("cliente_padrao")


def configure_instituicao_financeira(
    data: dict[str, Any], dry_run: bool = True
) -> str:
    if dry_run:
        return dry_run_result("instituicao_financeira", data)
    # Real flow after Codegen: find -> create/edit/skip -> fill -> save -> reread.
    require_captured_selectors("instituicao_financeira")
