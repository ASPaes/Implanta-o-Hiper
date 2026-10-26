from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server


def test_operator_panel_import_simulation_and_progress(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1366, "height": 1000})
                base = f"http://127.0.0.1:{server.server_port}"
                page.goto(base)
                page.get_by_role("button", name="Importar", exact=True).click()
                expect(page.get_by_role("heading", name="Revise os dados", exact=True)).to_be_visible()
                page.goto(base)
                page.get_by_role("link", name="Hiper", exact=True).click()
                expect(page.get_by_role("heading", name="Conectar e implantar")).to_be_visible()
                expect(page.locator("#hiper-steps li")).to_have_count(7)
                page.get_by_role("button", name="Executar", exact=True).click()
                expect(page.locator("#deployment-status")).to_have_text("Etapas selecionadas concluídas", timeout=15000)
                expect(page.locator("#hiper-steps")).to_contain_text("Conferido")
                page.get_by_role("button", name="Retomar", exact=True).click()
                expect(page.locator("#deployment-status")).to_have_text("Etapas selecionadas concluídas", timeout=15000)
                expect(page.locator("#hiper-history")).to_contain_text("execucao_concluida")
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            finally:
                browser.close()
    finally:
        app.extensions["hiper"]["close"]()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
