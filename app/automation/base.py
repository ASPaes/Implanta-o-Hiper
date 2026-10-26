"""Shared automation contracts."""

from typing import Any


class SelectorsNotCapturedError(RuntimeError):
    """Raised whenever real mode is requested before Codegen capture."""


def dry_run_result(step_key: str, _: dict[str, Any]) -> str:
    return f"dry-run://{step_key}/simulado-confirmado"


def require_captured_selectors(step_key: str) -> None:
    raise SelectorsNotCapturedError(
        f"Modo real indisponível para '{step_key}': seletores do Hiper ainda "
        "não foram capturados via Playwright Codegen."
    )
