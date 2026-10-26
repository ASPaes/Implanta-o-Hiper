"""Navigation uses only supplied URLs or paths from captured profiles."""

import re
from urllib.parse import quote, urljoin, urlsplit

from app.automation.hiper.errors import HiperSelectorNotMapped
from app.automation.hiper.resolver import HiperStore, normalize_cnpj, verify_identity


class HiperNavigation:
    def __init__(self, page, base: str, profile, tenants, auth):
        self.page, self.base, self.profile = page, base, profile
        self.tenants, self.auth = tenants, auth

    async def goto(self, url: str):
        self.tenants.validate_url(url, self.base)
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.auth.check(self.page, self.base, expired=True)

    async def stores(self) -> list[HiperStore]:
        spec = self.profile.require("stores")
        if spec.get("path"):
            await self.goto(urljoin(self.base + "/", spec["path"]))
        elif spec.get("link"):
            await (await self.profile.unique(self.page, spec["link"])).click()
            await self.auth.check(self.page, self.base, expired=True)
        else:
            raise HiperSelectorNotMapped("Mapeie a navegação para a lista de filiais.")
        if spec.get("ready"):
            await self.profile.unique(self.page, spec["ready"])
        else:
            raise HiperSelectorNotMapped("Mapeie o marcador de lista de filiais carregada.")
        rows = self.profile.locator(self.page, spec["rows"])
        result = []
        for row in await rows.all():
            cnpj = normalize_cnpj(await self.profile.read(row, spec["cnpj"]))
            name = await self.profile.read(row, spec["name"])
            link = await self.profile.unique(row, spec["link_to_settings"])
            href = await link.get_attribute("href")
            if not href:
                raise HiperSelectorNotMapped("Link da filial não contém URL.")
            url = self.tenants.validate_url(urljoin(self.base + "/", href), self.base)
            if spec.get("id_attribute"):
                store_id = await row.get_attribute(spec["id_attribute"])
            else:
                pattern = spec.get("id_from_url_regex")
                match = re.search(pattern, urlsplit(url).path) if pattern else None
                store_id = match.group(1) if match else None
            if not store_id:
                raise HiperSelectorNotMapped("Não foi possível extrair o ID da filial.")
            result.append(HiperStore(store_id, name, cnpj, url))
        return result

    async def general(self, store: HiperStore):
        general = self.profile.require("general_data")
        if general.get("path_template"):
            path = general["path_template"].format(store_id=quote(store.id, safe=""))
            await self.goto(urljoin(self.base + "/", path))
        else:
            await self.goto(store.url)
        if general.get("link"):
            await (await self.profile.unique(self.page, general["link"])).click()
            await self.auth.check(self.page, self.base, expired=True)
        await self.profile.unique(self.page, general["cnpj"])

    async def identity(self, expected_cnpj: str) -> str:
        await self.auth.check(self.page, self.base, expired=True)
        cnpj = await self.profile.read(self.page, self.profile.require("general_data")["cnpj"])
        verify_identity(expected_cnpj, cnpj)
        return normalize_cnpj(cnpj)
