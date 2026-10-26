"""Async browser lifetime and per-tenant storage; manual login only."""

import asyncio
import hashlib
import os
import subprocess
import threading
from pathlib import Path

from app.automation.hiper.auth import HiperAuth
from app.automation.hiper.errors import HiperError
from app.automation.hiper.resolver import HiperTenantResolver
from app.automation.hiper.selectors import SelectorProfile


def private_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Resolve current user SID without printing it, and remove inherited ACLs.
        sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                             capture_output=True, text=True, check=True).stdout
        import csv
        user_sid = next(csv.reader([sid.strip()]))[1]
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        f"*{user_sid}:(OI)(CI)F"], capture_output=True, check=True)
    else:
        path.chmod(0o700)


class BrowserManager:
    def __init__(self, config: dict, profile: SelectorProfile | None = None):
        self.config = config
        self.profile = profile or SelectorProfile.load(config["HIPER_SELECTOR_PROFILE"])
        self.tenants = HiperTenantResolver(config.get("HIPER_ALLOW_LOCAL_TEST_URLS", False))
        self.auth = HiperAuth(self.profile, self.tenants)
        self.sessions: dict[str, tuple] = {}
        self.session_headless: dict[str, bool] = {}
        self.playwright = None

    def state_path(self, base: str) -> Path:
        directory = Path(self.config["HIPER_STORAGE_STATE_DIR"])
        private_directory(directory)
        return directory / (hashlib.sha256(base.encode()).hexdigest() + ".json")

    async def open(self, base: str, *, manual: bool = False):
        if base in self.sessions:
            browser, context, page = self.sessions[base]
            if (not page.is_closed() and browser.is_connected()
                    and not (manual and self.session_headless.get(base))):
                return page
            await browser.close()
            self.sessions.pop(base)
        if self.playwright is None:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
        state = self.state_path(base)
        options = {"headless": False if manual else self.config["HIPER_BROWSER_HEADLESS"]}
        if self.config.get("HIPER_BROWSER_EXECUTABLE"):
            options["executable_path"] = self.config["HIPER_BROWSER_EXECUTABLE"]
        browser = await self.playwright.chromium.launch(**options)
        try:
            context = await browser.new_context(storage_state=str(state) if state.exists() else None)
            context.set_default_timeout(self.config["HIPER_BROWSER_TIMEOUT_MS"])
            context.set_default_navigation_timeout(self.config["HIPER_BROWSER_TIMEOUT_MS"])
            page = await context.new_page()
            await page.goto(base, wait_until="domcontentloaded")
            self.sessions[base] = (browser, context, page)
            self.session_headless[base] = options["headless"]
            return page
        except Exception:
            await browser.close()
            raise

    async def status(self, base: str) -> dict:
        page = await self.open(base)
        probe = self.profile.data.get("auth_probe_path")
        if probe:
            from urllib.parse import urljoin
            url = self.tenants.validate_url(urljoin(base + "/", probe), base)
            await page.goto(url, wait_until="domcontentloaded")
        else:
            await page.reload(wait_until="domcontentloaded")
        await self.auth.check(page, base)
        _, context, _ = self.sessions[base]
        path = self.state_path(base)
        temporary = path.with_suffix(".tmp")
        try:
            await context.storage_state(path=str(temporary), indexed_db=True)
            if os.name != "nt":
                temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"status": "authenticated", "hiper_base_url": base}

    async def close(self):
        for browser, _, _ in list(self.sessions.values()):
            await browser.close()
        self.sessions.clear()
        self.session_headless.clear()
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None


class AsyncRuntime:
    """Flask threads submit coroutines; all browser objects stay on one loop."""

    def __init__(self):
        self.loop = None
        self.thread = None
        self.ready = threading.Event()
        self.lock = threading.Lock()

    def _start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            def work():
                # Proactor on Windows supports Playwright subprocess pipes.
                self.loop = asyncio.ProactorEventLoop() if os.name == "nt" else asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                self.ready.set()
                self.loop.run_forever()
                self.loop.close()
            self.thread = threading.Thread(target=work, name="hiper-browser", daemon=True)
            self.thread.start()
        self.ready.wait(timeout=10)

    def call(self, coroutine, timeout: float = 120):
        self._start()
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise HiperError("A operação excedeu o tempo limite; confira o status antes de retomar.") from None

    def close(self, manager):
        if self.loop and self.thread.is_alive():
            self.call(manager.close())
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=10)
