import asyncio
import json
from pathlib import Path

import pytest

from hiper_support import local_hiper, manager_for
from app.automation.hiper.errors import (
    HiperAuthenticationRequired, HiperSessionExpired, HiperSelectorNotMapped,
    HiperSaveFailed, HiperStoreIdentityMismatch,
)
from app.automation.hiper.evidence import capture_evidence, describe_page
from app.automation.hiper.navigation import HiperNavigation
from app.automation.hiper.resolver import HiperStoreResolver
from app.automation.hiper.steps import DadosLojaStep
from app.automation.hiper.selectors import SelectorProfile


async def setup(manager, base):
    page = await manager.open(base)
    await page.goto(base + "/login")
    await manager.status(base)
    navigation = HiperNavigation(page, base, manager.profile, manager.tenants, manager.auth)
    stores = await navigation.stores()
    store = HiperStoreResolver().choose(stores, "12345678000195")
    company = {"cnpj": "12345678000195", "trade_name": "Nova loja", "email": "new@example.test"}
    return page, navigation, store, company


def test_real_save_reload_idempotency_and_read_only_dry_run(tmp_path, local_hiper):
    base, state = local_hiper
    async def scenario():
        manager = manager_for(tmp_path)
        try:
            _, nav, store, company = await setup(manager, base)
            step = DadosLojaStep(nav, store, company)
            dry = await step.run("dry_run")
            assert dry.status == "success" and state["writes"] == 0
            assert state["trade_name"] == "Nome anterior"
            real = await step.run("real")
            assert real.status == "success" and state["writes"] == 1
            assert state["trade_name"] == "Nova loja" and state["email"] == "new@example.test"
            repeat = await step.run("real")
            assert repeat.status == "skipped" and state["writes"] == 1
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_storage_reuse_and_expiration(tmp_path, local_hiper):
    base, state = local_hiper
    async def scenario():
        manager = manager_for(tmp_path)
        try:
            await setup(manager, base)
            assert manager.state_path(base).is_file()
        finally:
            await manager.close()
        new = manager_for(tmp_path)
        try:
            assert (await new.status(base))["status"] == "authenticated"
            state["authenticated"] = False
            with pytest.raises(HiperAuthenticationRequired):
                await new.status(base)
        finally:
            await new.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["cnpj", "save", "expired", "selector"])
def test_browser_failures_never_report_success(tmp_path, local_hiper, failure):
    base, state = local_hiper
    async def scenario():
        manager = manager_for(tmp_path)
        try:
            page, nav, store, company = await setup(manager, base)
            if failure == "cnpj":
                state["actual_cnpj"] = "11222333000144"
                error = HiperStoreIdentityMismatch
            elif failure == "save":
                state["ignore_save"] = True
                error = HiperSaveFailed
            elif failure == "expired":
                state["authenticated"] = False
                error = HiperSessionExpired
            else:
                manager.profile.data["general_data"]["fields"]["trade_name"] = {"label": "Seletor inexistente"}
                error = HiperSelectorNotMapped
            with pytest.raises(error):
                await DadosLojaStep(nav, store, company).run("real")
            if failure != "save":
                assert state["writes"] == 0
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_inspection_and_evidence_exclude_secrets(tmp_path, local_hiper):
    base, state = local_hiper
    async def scenario():
        manager = manager_for(tmp_path)
        try:
            page, nav, store, _ = await setup(manager, base)
            await nav.general(store)
            snapshot = await describe_page(page)
            assert "fixture-secret-do-not-export" not in json.dumps(snapshot)
            assert "test-authorized" not in json.dumps(snapshot)
            report = await capture_evidence(manager, page, base, 1, "loja_config", HiperSaveFailed("Gravação não confirmada."))
            metadata = json.loads(Path(report).read_text(encoding="utf-8"))
            assert metadata["screenshot"] and (Path(report).parent / metadata["screenshot"]).is_file()
            assert "fixture-secret-do-not-export" not in Path(report).read_text(encoding="utf-8")
            state["authenticated"] = False
            await page.goto(base)
            report = await capture_evidence(manager, page, base, 1, "loja_config", HiperAuthenticationRequired("Login necessário."))
            assert "screenshot" not in json.loads(Path(report).read_text(encoding="utf-8"))
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_empty_profile_and_unsafe_field_are_explicitly_blocked():
    with pytest.raises(HiperSelectorNotMapped):
        SelectorProfile().require("authenticated")
    with pytest.raises(HiperSelectorNotMapped):
        SelectorProfile({"authenticated": {"role": "button", "name": "Whatever"}})
