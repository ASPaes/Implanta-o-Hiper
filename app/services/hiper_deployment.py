"""Async deployment execution; browser and business rules are outside HTTP."""

import asyncio
import json
import logging
import uuid
from contextlib import suppress

from app.automation.hiper.errors import (
    HiperError, HiperRealModeDisabled, HiperSelectorNotMapped,
    HiperSaveFailed, HiperDeploymentAlreadyRunning,
)
from app.automation.hiper.evidence import capture_evidence
from app.automation.hiper.navigation import HiperNavigation
from app.automation.hiper.resolver import (
    HiperStore, HiperStoreResolver, normalize_cnpj, verify_identity,
)
from app.automation.hiper.steps import DadosLojaStep
from app.models import STEP_KEYS
from app.persistence.hiper import HiperRepository
from app.persistence.repositories import DeploymentRepository, StepRepository


log = logging.getLogger("hiper.deployment")


class HiperDeploymentService:
    def __init__(self, config: dict, manager):
        self.config, self.manager = config, manager
        self.deployments = DeploymentRepository(config["DATABASE"])
        self.steps = StepRepository(config["DATABASE"])
        self.repo = HiperRepository(config["DATABASE"])
        self.tasks: dict[int, asyncio.Task] = {}

    def tenant(self, deployment, override: str = "") -> str:
        # Resolved tenant is also a hint, never override conflicting contract values.
        data = dict(deployment.data)
        if deployment.hiper_base_url:
            data.setdefault("hiper_base_url", deployment.hiper_base_url)
        return self.manager.tenants.resolve(data, override, self.config["HIPER_DEFAULT_DOMAIN"])

    def navigation(self, page, base: str):
        return HiperNavigation(page, base, self.manager.profile, self.manager.tenants, self.manager.auth)

    async def session(self, deployment_id: int, domain: str = "", *, manual=False):
        deployment = self.deployments.get(deployment_id)
        base = self.tenant(deployment, domain)
        with self.repo.lock("tenant:" + base, "session:" + uuid.uuid4().hex):
            if manual:
                await self.manager.open(base, manual=True)
                return {"status": "awaiting_auth", "hiper_base_url": base,
                        "message": "Conclua o login manual no navegador e verifique a sessão."}
            return await self.manager.status(base)

    async def resolve(self, deployment_id: int, domain: str = "", selected_id: str = "") -> dict:
        deployment = self.deployments.get(deployment_id)
        base = self.tenant(deployment, domain)
        with self.repo.lock("tenant:" + base, "resolve:" + uuid.uuid4().hex):
            page = await self.manager.open(base)
            await self.manager.auth.check(page, base)
            navigation = self.navigation(page, base)
            company = deployment.data.get("company") or {}
            cnpj = normalize_cnpj(company.get("cnpj", ""))
            direct_url = deployment.data.get("hiper_store_url")
            hinted_id = str(deployment.data.get("hiper_store_id") or "")
            # Explicit operator selection always beats a supplied shortcut.
            if not selected_id and (direct_url or hinted_id):
                if direct_url:
                    self.manager.tenants.validate_url(direct_url, base)
                if not hinted_id and direct_url:
                    import re
                    from urllib.parse import urlsplit
                    pattern = self.manager.profile.require("stores").get("id_from_url_regex")
                    match = re.search(pattern, urlsplit(direct_url).path) if pattern else None
                    hinted_id = match.group(1) if match else ""
                elif direct_url and hinted_id:
                    import re
                    from urllib.parse import urlsplit
                    pattern = self.manager.profile.require("stores").get("id_from_url_regex")
                    match = re.search(pattern, urlsplit(direct_url).path) if pattern else None
                    if not match or match.group(1) != hinted_id:
                        raise HiperError("ID fornecido diverge do ID extraído da URL da filial.")
                if not hinted_id:
                    raise HiperSelectorNotMapped("Mapeie extração do ID da URL fornecida.")
                store = HiperStore(hinted_id, "", cnpj, direct_url or base,
                                   "provided_url_cnpj" if direct_url else "provided_id_cnpj")
                if not direct_url and not self.manager.profile.require("general_data").get("path_template"):
                    raise HiperSelectorNotMapped("Mapeie rota para resolver o ID informado.")
                await navigation.general(store)
            else:
                stores = await navigation.stores()
                store = HiperStoreResolver().choose(
                    stores, cnpj, selected_id=selected_id,
                    mapped_id=self.repo.mapping(deployment.contract_id, cnpj, base),
                    company_name=company.get("legal_name", ""),
                )
                await navigation.general(store)
            actual = await navigation.identity(cnpj)
            name_spec = self.manager.profile.require("general_data").get("store_name")
            name = await self.manager.profile.read(page, name_spec) if name_spec else store.name
            if not name:
                raise HiperSelectorNotMapped("Mapeie o nome da filial na tela de dados gerais.")
            store = HiperStore(store.id, name, actual, page.url, store.method)
            self.manager.tenants.validate_url(store.url, base)
            self.repo.context(deployment_id, base, store)
            self.repo.audit(deployment_id, f"filial_verificada contrato:{deployment.contract_id} cnpj:{actual} tenant:{base} filial:{store.id}")
            return {"hiper_base_url": base, "store": store.public(), "status": "verified"}

    async def start(self, deployment_id: int, *, mode: str = "simulation",
                    selected_steps: list[str] | None = None, confirmed: bool = False,
                    operator: str = "", accountant_approved: bool = False, resume: bool = False) -> dict:
        deployment = self.deployments.get(deployment_id)
        if deployment_id in self.tasks and not self.tasks[deployment_id].done():
            raise HiperDeploymentAlreadyRunning("Esta implantação já está em execução.")
        if mode not in {"simulation", "dry_run", "real"}:
            raise HiperError("Modo deve ser simulation, dry_run ou real.")
        keys = selected_steps if selected_steps is not None else ["loja_config"]
        if not keys or len(set(keys)) != len(keys) or any(key not in STEP_KEYS for key in keys):
            raise HiperError("Selecione etapas conhecidas, sem duplicatas.")
        # Preserve dependency order regardless of the client's list ordering.
        keys = [key for key in STEP_KEYS if key in keys]
        base = None
        if mode != "simulation":
            base = self.tenant(deployment)
            if not deployment.hiper_store_id or not deployment.store_verified_at:
                raise HiperError("Localize e valide a filial antes da execução com navegador.")
            verify_identity(deployment.data["company"]["cnpj"], deployment.hiper_store_cnpj)
        if mode == "real":
            if (not self.config["REAL_HIPER_AUTOMATION_ENABLED"] or not confirmed
                    or not operator.strip() or deployment.contract_source != "api"):
                raise HiperRealModeDisabled("Modo real exige habilitação, contrato de API, operador e confirmação explícita.")
            if "produto_ncm" in keys and not accountant_approved:
                raise HiperError("A etapa de NCM exige accountant_approved=true; automação fiscal ainda não mapeada.")
        owner = uuid.uuid4().hex
        resources = [f"deployment:{deployment_id}"]
        if base:
            resources += ["tenant:" + base, f"store:{base}:{deployment.hiper_store_id}"]
        acquired = []
        try:
            for resource in resources:
                self.repo.acquire(resource, owner)
                acquired.append(resource)
            if mode == "real":
                self.deployments.confirm_account(deployment_id, deployment.hiper_store_name, operator)
            self.repo.plan(deployment_id, mode, keys)
            self.deployments.update_status(deployment_id, "running")
            self.repo.audit(deployment_id, f"execucao_iniciada modo:{mode} etapas:{','.join(keys)}", operator or "operador")
            if base:
                self.repo.audit(deployment_id, json.dumps({
                    "contract": deployment.contract_id, "company": deployment.data["company"].get("legal_name"),
                    "cnpj": deployment.data["company"]["cnpj"], "domain": base,
                    "store": deployment.hiper_store_name, "store_cnpj": deployment.hiper_store_cnpj,
                    "store_id": deployment.hiper_store_id, "environment": deployment.environment,
                }, ensure_ascii=False), operator or "operador")
            task = asyncio.create_task(self._run(deployment_id, mode, keys, base, owner, resources, resume))
            self.tasks[deployment_id] = task
            return {"deployment_id": deployment_id, "status": "running", "mode": mode}
        except BaseException:
            for resource in acquired:
                self.repo.release(resource, owner)
            raise

    async def _heartbeat(self, resources, owner):
        while True:
            # Lease maintenance timer, not a browser synchronization sleep.
            await asyncio.sleep(30)
            for resource in resources:
                self.repo.renew(resource, owner)

    async def _run(self, deployment_id, mode, keys, base, owner, resources, resume):
        page = None
        key = keys[0]
        heartbeat = asyncio.create_task(self._heartbeat(resources, owner))
        def guard():
            for resource in resources:
                self.repo.renew(resource, owner)
        try:
            deployment = self.deployments.get(deployment_id)
            if mode != "simulation":
                page = await self.manager.open(base)
                await self.manager.auth.check(page, base, expired=True)
                store = HiperStore(deployment.hiper_store_id, deployment.hiper_store_name,
                                   deployment.hiper_store_cnpj, deployment.hiper_store_url)
                navigation = self.navigation(page, base)
                # Recheck tenant/store before resuming even if prefix steps are complete.
                await navigation.general(store)
                await navigation.identity(deployment.data["company"]["cnpj"])
            for key in keys:
                guard()
                if self.deployments.get(deployment_id).pause_requested:
                    self.deployments.update_status(deployment_id, "paused")
                    self.repo.audit(deployment_id, "execucao_pausada")
                    return
                existing = self.steps.get(deployment_id, key)
                if (existing.execution_mode == mode and existing.status in {"success", "skipped"}
                        and (mode == "simulation" or resume)):
                    continue
                self.steps.mark_running(deployment_id, key, mode=mode)
                log.info(json.dumps({"deployment_id": deployment_id, "contract_id": deployment.contract_id,
                                     "step": key, "mode": mode, "status": "running"}))
                if mode == "simulation":
                    self.repo.step_result(deployment_id, key, mode, "success", f"simulation://{key}/sem-navegador")
                    await asyncio.sleep(0)  # Yield for cooperative pause/status requests.
                    continue
                if key != "loja_config":
                    raise HiperSelectorNotMapped(f"Etapa real ainda não mapeada: {key}.")
                result = await DadosLojaStep(navigation, store, deployment.data["company"], guard=guard).run(mode)
                self.repo.step_result(deployment_id, key, mode, result.status, result.message)
            self.deployments.update_status(deployment_id, "completed")
            self.repo.audit(deployment_id, f"execucao_concluida modo:{mode}")
        except asyncio.CancelledError:
            self.repo.step_result(deployment_id, key, mode, "waiting_user", message="Execução interrompida; retome para reinspecionar.")
            self.deployments.update_status(deployment_id, "paused")
            raise
        except Exception as raw:
            error = raw if isinstance(raw, HiperError) else HiperSaveFailed("Falha de automação; confira a evidência e retome após revisar a sessão.")
            evidence = ""
            if mode != "simulation":
                with suppress(Exception):
                    evidence = await capture_evidence(self.manager, page, base, deployment_id, key, error)
            self.repo.step_result(deployment_id, key, mode, error.status, evidence, error.code, str(error))
            self.deployments.update_status(deployment_id, error.status)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, HiperError):
                await heartbeat
            for resource in resources:
                self.repo.release(resource, owner)

    async def shutdown(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        await self.manager.close()
