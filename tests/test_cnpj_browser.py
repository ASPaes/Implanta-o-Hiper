"""Optional end-to-end check of the browser form (RUN_BROWSER_TESTS=1)."""

import os
from pathlib import Path
from threading import Thread

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from app import create_app
from test_ui import review_payload


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="browser smoke test is optional")
def test_cnpj_button_autofill_and_not_found_in_browser(tmp_path, monkeypatch):
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if not chrome.is_file():
        pytest.skip("Chrome is not installed at the expected path")

    fixtures = Path(__file__).parents[1] / "fixtures" / "contracts"
    app = create_app({
        "TESTING": True, "SECRET_KEY": "test", "DATABASE": str(tmp_path / "browser.db"),
        "FIXTURES_PATH": str(fixtures), "CONTRACT_SOURCE": "fixture", "DRY_RUN": True,
    })

    def fake_get(url, *, headers, timeout):
        if url.endswith("/19131243000197"):
            return httpx.Response(200, json={
                "razao_social": "Empresa Consultada Ltda", "nome_fantasia": "Consultada",
                "logradouro": "Rua da API", "bairro": "Centro",
                "municipio": "São Paulo", "uf": "SP",
            })
        if url.endswith("/11222333000144"):
            return httpx.Response(200, json={
                "razao_social": "Banco Consultado S.A.",
                "nome_fantasia": "Banco Consultado", "cep": "01001000",
                "numero": "200",
            })
        return httpx.Response(404)

    monkeypatch.setattr(httpx, "get", fake_get)
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                page.locator('[name="contract_id"]').fill("1042")
                page.get_by_role("button", name="Importar").click()
                cnpj = page.locator('[name="company.cnpj"]')
                cnpj.fill("19131243000197")
                page.wait_for_timeout(150)
                expect(page.locator("#cnpj-lookup-status")).to_have_text("")
                page.locator('[data-cnpj-target="company"]').click()
                expect(page.locator("#cnpj-lookup-status")).to_have_text(
                    "Dados da empresa preenchidos."
                )
                assert page.locator('[name="company.legal_name"]').input_value() == "Empresa Consultada Ltda"
                assert page.locator('[name="company.trade_name"]').input_value() == "Consultada"
                assert page.locator('[name="company.logradouro"]').input_value() == "Rua da API"
                assert page.locator('[name="company.bairro"]').input_value() == "Centro"
                assert page.locator('[name="company.municipio"]').input_value() == "São Paulo"
                assert page.locator('[name="company.uf"]').input_value() == "SP"

                cnpj.fill("00000000000000")
                page.locator('[data-cnpj-target="company"]').click()
                expect(page.locator("#cnpj-lookup-status")).to_have_text("CNPJ não encontrado.")

                cnpj.fill("123")
                page.locator('[data-cnpj-target="company"]').click()
                expect(page.locator("#cnpj-lookup-status")).to_have_text(
                    "Informe um CNPJ com 14 dígitos."
                )

                bank_cnpj = page.locator('[name="instituicao_financeira.cnpj_banco"]')
                bank_cnpj.fill("11222333000144")
                page.locator('[data-cnpj-target="bank"]').click()
                expect(page.locator("#bank-cnpj-lookup-status")).to_have_text(
                    "Dados do banco preenchidos."
                )
                assert page.locator('[name="instituicao_financeira.bank_name"]').input_value() == "Banco Consultado S.A."
                assert page.locator('[name="instituicao_financeira.nome_fantasia"]').input_value() == "Banco Consultado"
                assert page.locator('[name="instituicao_financeira.cep"]').input_value() == "01001000"
                assert page.locator('[name="instituicao_financeira.numero"]').input_value() == "200"
                assert page.locator('[name="fiscal.cliente_fornecedor"]').input_value() == "Banco Consultado S.A."
                expect(page.locator('[name="bandeiras_cartao.cliente_fornecedor"]')).to_have_value("Banco Consultado S.A.")
                page.locator('[name="instituicao_financeira.bank_name"]').fill("Banco Editado")
                expect(page.locator('[name="bandeiras_cartao.cliente_fornecedor"]')).to_have_value("Banco Editado")
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="browser smoke test is optional")
def test_add_ten_users_in_browser_and_reopen_review(app):
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if not chrome.is_file():
        pytest.skip("Chrome is not installed at the expected path")
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                page.get_by_role("button", name="Importar").click()
                review_url = page.url
                expect(page.locator("#card-brand-settings [data-card-entry]")).to_have_count(15)
                expect(page.locator('[name="bandeiras_cartao.credenciadora"]')).to_have_value("")
                for name, value in review_payload().items():
                    field = page.locator(f'[name="{name}"]')
                    if field.get_attribute("readonly") is not None:
                        continue
                    if name == "usuarios.perfil":
                        field.select_option(value)
                    else:
                        field.fill(value)
                add_button = page.get_by_role("button", name="Adicionar usuário")
                expect(add_button).to_have_text("+")
                for index in range(1, 10):
                    add_button.click()
                    blocks = page.locator("#users-list [data-user-block]")
                    expect(blocks).to_have_count(index + 1)
                    new_block = blocks.nth(index)
                    expect(new_block.locator('[name="usuarios.nome"]')).to_be_focused()
                    expect(new_block.locator('[name="usuarios.nome"]')).to_have_value("")
                    new_block.locator('[name="usuarios.nome"]').fill(f"Pessoa {index + 1}")
                    new_block.locator('[name="usuarios.usuario"]').fill(f"pessoa.{index + 1}")
                    new_block.locator('[name="usuarios.perfil"]').select_option("caixa")
                expect(page.locator('[name="usuarios.usuario"]').first).to_have_value("cliente.piloto")
                acquirer = page.locator('[name="bandeiras_cartao.credenciadora"]')
                acquirer.fill("")
                page.get_by_role("button", name="Validar e continuar").click()
                expect(page).to_have_url(review_url)
                assert not acquirer.evaluate("field => field.validity.valid")
                acquirer.fill("Credenciadora Escolhida")
                blocks = page.locator("#users-list [data-user-block]")
                blocks.nth(4).get_by_role("button", name="Remover usuário").click()
                expect(blocks).to_have_count(9)
                blocks.first.get_by_role("button", name="Remover usuário").click()
                expect(blocks).to_have_count(8)
                expect(page.locator('[name="usuarios.usuario"]').first).to_have_value("pessoa.2")
                expect(add_button).to_have_count(1)
                expect(acquirer).to_have_value("Credenciadora Escolhida")
                add_button.click()
                blocks.last.locator('[name="usuarios.nome"]').fill("Pessoa extra")
                blocks.last.locator('[name="usuarios.usuario"]').fill("pessoa.extra")
                blocks.last.locator('[name="usuarios.perfil"]').select_option("gerente")
                page.get_by_role("button", name="Validar e continuar").click()
                expect(page).to_have_url(review_url.replace("/review", "/execute"))
                expect(page.locator('[name="usuarios.senha"]')).to_have_count(9)
                page.goto(review_url)
                expect(blocks).to_have_count(9)
                expect(page.locator('[name="usuarios.usuario"]').last).to_have_value("pessoa.extra")
                expect(add_button).to_have_count(1)
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="browser smoke test is optional")
def test_caixas_add_remove_and_new_fiscal_settings_in_browser(app):
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if not chrome.is_file():
        pytest.skip("Chrome is not installed at the expected path")
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                page.get_by_role("button", name="Importar").click()
                review_url = page.url
                expect(page.locator('[name="fiscal.conta_bancaria"]')).to_have_value("")
                for name, value in review_payload().items():
                    field = page.locator(f'[name="{name}"]')
                    if field.get_attribute("readonly") is not None:
                        continue
                    if name == "usuarios.perfil":
                        field.select_option(value)
                    else:
                        field.fill(value)
                add_button = page.get_by_role("button", name="Adicionar caixa")
                blocks = page.locator("#caixas-list [data-caixa-block]")
                expect(blocks.first.get_by_role("button", name="Remover caixa")).to_be_disabled()
                expect(page.get_by_role("button", name="Remover usuário")).to_be_disabled()
                for index in range(3):
                    add_button.click()
                    expect(blocks).to_have_count(index + 2)
                    expect(blocks.last.locator('[name="fiscal.caixas.numero_caixa"]')).to_be_focused()
                    blocks.last.locator('[name="fiscal.caixas.numero_caixa"]').fill(str(index + 5))
                    blocks.last.locator('[name="fiscal.caixas.serie_fiscal"]').fill(str(index + 15))
                blocks.nth(1).get_by_role("button", name="Remover caixa").click()
                blocks.last.get_by_role("button", name="Remover caixa").click()
                expect(blocks).to_have_count(2)
                expect(blocks.last.locator('[name="fiscal.caixas.numero_caixa"]')).to_have_value("6")
                expect(blocks.last.locator('[name="fiscal.caixas.serie_fiscal"]')).to_have_value("16")
                blocks.first.get_by_role("button", name="Remover caixa").click()
                expect(blocks).to_have_count(1)
                expect(blocks.first.get_by_role("button", name="Remover caixa")).to_be_disabled()
                add_button.click()
                blocks.last.locator('[name="fiscal.caixas.numero_caixa"]').fill("8")
                blocks.last.locator('[name="fiscal.caixas.serie_fiscal"]').fill("18")
                page.locator('[name="fiscal.nfce.numero_identificacao"]').fill("000001")
                page.locator('[name="fiscal.nfce.token"]').fill("private-browser-csc")
                page.locator('[name="fiscal.conta_bancaria"]').fill("")
                switch = page.locator('[name="fiscal.imprimir_nome_fantasia"]')
                expect(switch).not_to_be_checked()
                switch.check()
                page.get_by_role("button", name="Validar e continuar").click()
                expect(page).to_have_url(review_url.replace("/review", "/execute"))
                page.goto(review_url)
                expect(blocks).to_have_count(2)
                expect(blocks.first.locator('[name="fiscal.caixas.numero_caixa"]')).to_have_value("6")
                expect(blocks.last.locator('[name="fiscal.caixas.serie_fiscal"]')).to_have_value("18")
                expect(switch).to_be_checked()
                expect(page.locator('[name="fiscal.nfce.numero_identificacao"]')).to_have_value("000001")
                expect(page.locator('[name="fiscal.nfce.token"]')).to_have_value("")
                expect(page.locator("#nfce-settings")).to_contain_text("Token disponível nesta sessão")
                expect(page.locator('[name="fiscal.conta_bancaria"]')).to_have_value("")
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
