"""Utilities that prevent credentials and secrets from being persisted."""

import re
from typing import Any


SECRET_PARTS = (
    "password", "senha", "secret", "token", "api_key", "apikey", "csc",
    "certificado",
    "cookie", "authorization", "storage_state", "credential",
)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(part in key.lower() for part in SECRET_PARTS)
            else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def sanitize_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+",
        r"\1[REDACTED]", text,
    )
    text = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)(password|senha|secret|token|api[_-]?key|csc|certificado|cookie|storage_state)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    return text[:1000]
