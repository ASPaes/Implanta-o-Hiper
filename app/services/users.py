"""Read both existing single-user contracts and multi-user reviews."""

from typing import Any


def user_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    users = data.get("usuarios", {})
    if isinstance(users, dict):
        return [users]
    if isinstance(users, list) and users:
        return users
    return [{}]


def user_error_key(index: int, field: str) -> str:
    return f"usuarios.{field}" if index == 0 else f"usuarios.{index}.{field}"
