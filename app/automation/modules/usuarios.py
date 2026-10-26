"""User creation boundary. The password lives only during this step."""

from typing import Any

from app.automation.base import dry_run_result, require_captured_selectors


def configure_usuario(
    data: dict[str, Any], password: str, dry_run: bool = True,
) -> str:
    if not password:
        raise ValueError("Informe a senha do usuário antes de executar.")
    if dry_run:
        return dry_run_result("usuarios", data)
    # Real flow after Codegen: find user -> create/edit -> assign profile -> save -> reread.
    require_captured_selectors("usuarios")
