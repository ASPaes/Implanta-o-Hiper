"""Prove authenticated tenant context using captured UI markers."""

from app.automation.hiper.errors import HiperAuthenticationRequired, HiperSessionExpired


class HiperAuth:
    def __init__(self, profile, tenant_resolver):
        self.profile = profile
        self.tenants = tenant_resolver

    async def check(self, page, base: str, *, expired: bool = False):
        # Login may redirect through a central identity provider. It remains manual.
        if page.is_closed():
            raise HiperAuthenticationRequired("O navegador foi fechado; abra uma nova sessão.")
        marker = self.profile.require("authenticated")
        try:
            self.tenants.assert_session(page.url, base)
        except Exception:
            error = HiperSessionExpired if expired else HiperAuthenticationRequired
            raise error("A sessão não está autenticada no tenant esperado.") from None
        login_marker = self.profile.data.get("login_required")
        if login_marker:
            locator = self.profile.locator(page, login_marker)
            if await locator.count() and await locator.first.is_visible():
                error = HiperSessionExpired if expired else HiperAuthenticationRequired
                raise error("Login manual necessário no Hiper.")
        locator = self.profile.locator(page, marker)
        try:
            await locator.wait_for(state="visible")
        except Exception:
            error = HiperSessionExpired if expired else HiperAuthenticationRequired
            raise error("O marcador de sessão autenticada não foi encontrado.") from None
        if await locator.count() != 1:
            raise HiperAuthenticationRequired("Não foi possível confirmar uma sessão única.")
