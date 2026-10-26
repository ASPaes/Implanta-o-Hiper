"""Accountant automation boundary."""

from typing import Any

from app.automation.base import dry_run_result, require_captured_selectors


def configure_contador(data: dict[str, Any], dry_run: bool = True) -> str:
    if dry_run:
        return dry_run_result("contador", data)
    # Real flow after Codegen: find -> create/edit/skip -> fill -> save -> reread.
    require_captured_selectors("contador")
