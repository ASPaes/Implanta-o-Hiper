"""Default product NCM automation boundary."""

from typing import Any

from app.automation.base import dry_run_result, require_captured_selectors


def configure_produto_ncm(data: dict[str, Any], dry_run: bool = True) -> str:
    if dry_run:
        return dry_run_result("produto_ncm", data)
    # Real flow after Codegen: find -> edit/skip -> fill -> save -> reread.
    require_captured_selectors("produto_ncm")
