"""A local, mutable UI exercises real browser writes without touching Hiper."""

import json
from pathlib import Path
from threading import Thread

import pytest
from flask import Flask, make_response, render_template, request
from werkzeug.serving import make_server

from app.automation.hiper.browser import BrowserManager
from app.automation.hiper.selectors import SelectorProfile
from app.config import hiper_config


@pytest.fixture
def local_hiper():
    fixture_dir = Path(__file__).parent / "fixtures"
    web = Flask("local-hiper", template_folder=str(fixture_dir))
    state = {"authenticated": True, "writes": 0, "ignore_save": False, "duplicate": False,
             "actual_cnpj": "12.345.678/0001-95", "trade_name": "Nome anterior", "email": "old@example.test"}
    def authenticated():
        return state["authenticated"] and request.cookies.get("session") == "test-authorized"
    @web.get("/login")
    def login():
        # Controlled test sign-in only; production manager NEVER logs in.
        response = make_response('<div data-testid="authenticated">Autorizado</div>')
        response.set_cookie("session", "test-authorized")
        return response
    @web.get("/")
    def root():
        return '<div data-testid="authenticated">Autorizado</div>' if authenticated() else '<div data-testid="login-required">Login necessário</div>'
    @web.get("/stores")
    def stores():
        if not authenticated():
            return root()
        row = '<div data-store-id="{id}"><span data-testid="row-name">Loja local</span><span data-testid="row-cnpj">12.345.678/0001-95</span><a href="/stores/{id}/general">Configurar</a></div>'
        return '<div data-testid="authenticated">Autorizado</div><div data-testid="store-list">' + row.format(id="one") + (row.format(id="two") if state["duplicate"] else "") + '</div>'
    @web.get("/stores/<store_id>/general")
    def general(store_id):
        if not authenticated():
            return root()
        return render_template("hiper-general.html", store={"id": store_id, "name": "Loja local",
            "cnpj": state["actual_cnpj"], "trade_name": state["trade_name"], "email": state["email"]})
    @web.post("/save/<store_id>")
    def save(store_id):
        if not authenticated():
            return {}, 401
        state["writes"] += 1
        if not state["ignore_save"]:
            state.update(request.get_json())
        return {}
    server = make_server("127.0.0.1", 0, web, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def manager_for(tmp_path, **overrides):
    profile = SelectorProfile.load(str(Path(__file__).parent / "fixtures/hiper-profile.json"))
    config = hiper_config(tmp_path)
    config.update(HIPER_BROWSER_HEADLESS=True, HIPER_BROWSER_TIMEOUT_MS=1500,
                  HIPER_ALLOW_LOCAL_TEST_URLS=True,
                  HIPER_STORAGE_STATE_DIR=str(tmp_path / "sessions"),
                  HIPER_SCREENSHOT_DIR=str(tmp_path / "artifacts"))
    config.update(overrides)
    return BrowserManager(config, profile)
