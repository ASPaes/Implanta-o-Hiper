"""Evidence contains no form values, cookies, scripts or storage state."""

import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.automation.hiper.browser import private_directory
from app.persistence.repositories import utc_now
from app.security.redaction import sanitize_text


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


async def describe_page(page) -> dict:
    # Deliberately export a small allowlist rather than raw authenticated HTML.
    data = await page.evaluate("""() => {
      const labelText = el => {
        const clone = el.cloneNode(true);
        clone.querySelectorAll('input,textarea,select,[contenteditable],script,style').forEach(child => child.remove());
        return clone.textContent.trim();
      };
      return ({
      title: document.title,
      elements: [...document.querySelectorAll('button,label,[role],input,select,textarea')]
        .map(el => ({tag:el.tagName.toLowerCase(), role:el.getAttribute('role') || '',
          label: el.tagName === 'LABEL' || el.tagName === 'BUTTON' ? labelText(el) : el.getAttribute('aria-label') || '',
          test_id:el.getAttribute('data-testid') || ''})),
      links: [...document.querySelectorAll('a[href]')]
        .map(el => ({label:labelText(el), url:el.href}))
    }); }""")
    for element in data["elements"]:
        element["label"] = sanitize_text(element["label"])
    for link in data["links"]:
        link["label"] = sanitize_text(link["label"])
        link["url"] = safe_url(link["url"])
    data["title"] = sanitize_text(data["title"])
    data["url"] = safe_url(page.url)
    return data


async def capture_evidence(manager, page, base: str, deployment_id: int, step: str, error) -> str:
    directory = Path(manager.config["HIPER_SCREENSHOT_DIR"]) / str(deployment_id)
    private_directory(directory)
    name = uuid.uuid4().hex
    report = {"deployment_id": deployment_id, "step": step, "timestamp": utc_now(),
              "error_code": error.code, "message": sanitize_text(str(error)),
              "url": safe_url(page.url) if page and not page.is_closed() else ""}
    if page and not page.is_closed():
        try:
            await manager.auth.check(page, base)
            # Mask ALL fields plus any captured sensitive containers. Login is never captured.
            masks = [page.locator("input,textarea,select,[contenteditable],canvas")]
            for spec in manager.profile.data.get("sensitive", []):
                masks.append(manager.profile.locator(page, spec))
            path = directory / f"{name}.png"
            await page.screenshot(path=str(path), mask=masks, full_page=False)
            report["screenshot"] = path.name
        except Exception:
            report["screenshot_omitted"] = "Página não autenticada ou captura indisponível."
    report_path = directory / f"{name}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(report_path)
