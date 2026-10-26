"""Browser session helpers. Login remains an exclusively manual action."""

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def persistent_session(user_data_dir: str) -> Iterator[object]:
    """Open a persistent visible browser where the operator logs in manually."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir, headless=False
        )
        try:
            yield context
        finally:
            context.close()


@contextmanager
def cdp_session(endpoint: str = "http://localhost:9222") -> Iterator[object]:
    """Attach to a Chrome that the operator opened and authenticated."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        try:
            yield browser
        finally:
            browser.close()
