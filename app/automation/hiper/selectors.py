"""Captured selector profiles; empty profile explicitly refuses automation."""

import json
from pathlib import Path

from app.automation.hiper.errors import HiperSelectorNotMapped


class SelectorProfile:
    def __init__(self, config: dict | None = None):
        self.data = config or {}
        if self.data and not self.data.get("captured_from"):
            raise HiperSelectorNotMapped("O perfil precisa documentar captured_from.")

    @classmethod
    def load(cls, path: str):
        if not path:
            return cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError()
            return cls(data)
        except (ValueError, OSError):
            raise HiperSelectorNotMapped("Não foi possível ler o perfil de seletores.") from None

    def require(self, key: str):
        value = self.data.get(key)
        if not value:
            raise HiperSelectorNotMapped(f"Mapeamento ausente: {key}.")
        return value

    def locator(self, root, spec: dict):
        if not isinstance(spec, dict):
            raise HiperSelectorNotMapped("Seletor precisa ser objeto JSON.")
        if "role" in spec and "name" in spec:
            return root.get_by_role(spec["role"], name=spec["name"], exact=True)
        if "label" in spec:
            return root.get_by_label(spec["label"], exact=True)
        if "test_id" in spec:
            return root.get_by_test_id(spec["test_id"])
        if "text" in spec:
            return root.get_by_text(spec["text"], exact=True)
        if "css" in spec:
            css = spec["css"]
            if any(part in css.lower() for part in ("nth-child", "xpath", "javascript:")):
                raise HiperSelectorNotMapped("Seletor frágil não permitido.")
            return root.locator(css)
        raise HiperSelectorNotMapped("Tipo de seletor não mapeado.")

    async def unique(self, root, spec: dict):
        specs = spec if isinstance(spec, list) else [spec]
        for candidate in specs:
            locator = self.locator(root, candidate)
            count = await locator.count()
            if count > 1:
                raise HiperSelectorNotMapped("Seletor encontrou elementos ambíguos.")
            if count == 1:
                await locator.wait_for(state="visible")
                return locator
        # Allow async rendering for primary captured selector, never random clicks.
        locator = self.locator(root, specs[0])
        try:
            await locator.wait_for(state="visible")
        except Exception:
            raise HiperSelectorNotMapped("Elemento mapeado não ficou visível.") from None
        if await locator.count() != 1:
            raise HiperSelectorNotMapped("Elemento mapeado não é único.")
        return locator

    async def read(self, root, spec: dict) -> str:
        locator = await self.unique(root, spec)
        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
        return (await locator.input_value() if tag in {"input", "textarea", "select"}
                else await locator.inner_text()).strip()
