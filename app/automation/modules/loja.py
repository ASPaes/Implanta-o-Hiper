"""Store and sales configuration automation boundaries."""

from typing import Any

from app.automation.base import dry_run_result, require_captured_selectors
from app.automation.modules.bandeiras_cartao import configure_bandeira_cartao
from app.services.card_brands import card_brand_targets


def configure_loja(data: dict[str, Any], dry_run: bool = True) -> str:
    if dry_run:
        return dry_run_result("loja_config", data)
    # Real flow after Codegen: find -> edit/skip -> fill -> save -> reread.
    require_captured_selectors("loja_config")


def configure_vendas(data: dict[str, Any], dry_run: bool = True) -> str:
    if dry_run:
        results = [
            configure_bandeira_cartao(target, dry_run=True)
            for target in card_brand_targets(data)
        ]
        return "; ".join([dry_run_result("config_vendas", data), *results])
    # Real flow after Codegen: find -> edit/skip -> fill -> save -> reread.
    require_captured_selectors("config_vendas")
