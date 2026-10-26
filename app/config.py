"""Conservative server configuration; secrets stay server-side."""

import os
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"true", "1", "yes", "on"}


def hiper_config(root: Path) -> dict:
    return {
        "REAL_HIPER_AUTOMATION_ENABLED": env_bool("REAL_HIPER_AUTOMATION_ENABLED"),
        "HIPER_BROWSER_HEADLESS": env_bool("HIPER_BROWSER_HEADLESS"),
        "HIPER_BROWSER_TIMEOUT_MS": int(os.getenv("HIPER_BROWSER_TIMEOUT_MS", "30000")),
        "HIPER_STORAGE_STATE_DIR": os.getenv("HIPER_STORAGE_STATE_DIR", str(root / "data/hiper-sessions")),
        "HIPER_SCREENSHOT_DIR": os.getenv("HIPER_SCREENSHOT_DIR", str(root / "data/hiper-artifacts")),
        "HIPER_SELECTOR_PROFILE": os.getenv("HIPER_SELECTOR_PROFILE", ""),
        "HIPER_DEFAULT_DOMAIN": os.getenv("HIPER_DEFAULT_DOMAIN", ""),
        "HIPER_DEBUG": env_bool("HIPER_DEBUG"),
        "HIPER_ALLOW_LOCAL_TEST_URLS": False,
        "HIPER_TRUSTED_HOSTS": os.getenv("HIPER_TRUSTED_HOSTS", "localhost,127.0.0.1").split(","),
    }
