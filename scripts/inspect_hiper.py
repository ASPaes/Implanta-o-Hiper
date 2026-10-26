"""Inspect an authorized session locally; never export raw authenticated HTML."""

import argparse
import asyncio
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import hiper_config
from app.automation.hiper.browser import BrowserManager, private_directory
from app.automation.hiper.evidence import describe_page
from app.automation.hiper.resolver import HiperTenantResolver


async def inspect(args):
    root = Path(__file__).resolve().parents[1]
    config = hiper_config(root)
    if args.profile:
        config["HIPER_SELECTOR_PROFILE"] = args.profile
    config["HIPER_BROWSER_HEADLESS"] = False
    manager = BrowserManager(config)
    base = HiperTenantResolver().origin(args.domain)
    try:
        page = await manager.open(base, manual=True)
        print("Conclua o login/MFA manual e abra a tela desejada. Não digite segredos neste terminal.")
        await asyncio.to_thread(input, "Pressione Enter para inspecionar a página atual: ")
        if args.debug or config["HIPER_DEBUG"]:
            await page.pause()
        manager.tenants.assert_session(page.url, base)
        # Selector-free discovery exports labels/roles only, never values/storage.
        data = await describe_page(page)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        directory = Path(config["HIPER_SCREENSHOT_DIR"]) / "inspection"
        private_directory(directory)
        (directory / "inspection.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.snapshot:
            document = "<!doctype html><meta charset='utf-8'><title>Inspeção sanitizada</title><pre>" + html.escape(json.dumps(data, ensure_ascii=False, indent=2)) + "</pre>"
            (directory / "inspection.html").write_text(document, encoding="utf-8")
        if manager.profile.data:
            await manager.auth.check(page, base)
            await manager.status(base)
            # status may navigate; operator reopens desired page for next inspection.
            masks = [page.locator("input,select,textarea,[contenteditable],canvas")]
            masks.extend(manager.profile.locator(page, spec) for spec in manager.profile.data.get("sensitive", []))
            await page.screenshot(path=str(directory / "inspection.png"), mask=masks)
            print("Sessão confirmada e salva; evidência local em diretório privado.")
        else:
            print("Sem perfil autenticado: screenshot e storage omitidos. Use os metadados para mapear o perfil.")
    finally:
        await manager.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="Subdomínio/URL autorizado do cliente Hiper")
    parser.add_argument("--profile", help="JSON de seletores capturados")
    parser.add_argument("--snapshot", action="store_true", help="Exportar HTML sanitizado de roles/labels")
    parser.add_argument("--debug", action="store_true", help="Abrir Playwright Inspector")
    args = parser.parse_args()
    try:
        asyncio.run(inspect(args))
    except Exception:
        print("Inspeção interrompida. Verifique domínio, navegador e perfil; nenhum erro bruto foi exportado.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
