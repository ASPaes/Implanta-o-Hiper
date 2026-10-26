"""JSON routes for local operator workflow; no browser logic in HTTP handlers."""

import atexit
import json
import secrets
from dataclasses import asdict
from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, render_template, request, session

from app.automation.hiper.browser import AsyncRuntime, BrowserManager
from app.automation.hiper.errors import (
    HiperError, HiperAuthenticationRequired, HiperSessionExpired, HiperTenantNotResolved,
    HiperStoreNotFound, HiperStoreAmbiguous, HiperStoreIdentityMismatch,
    HiperSelectorNotMapped, HiperSaveFailed, HiperRealModeDisabled,
)
from app.models import STEP_KEYS
from app.services.contract_adapter import ContractError
from app.services.hiper_deployment import HiperDeploymentService


def register_hiper(app, contracts):
    api = Blueprint("hiper", __name__)
    runtime = AsyncRuntime()
    manager = BrowserManager(app.config)
    service = HiperDeploymentService(app.config, manager)
    app.extensions["hiper"] = {"runtime": runtime, "manager": manager, "service": service}

    def csrf():
        if "hiper_csrf" not in session:
            session["hiper_csrf"] = secrets.token_urlsafe(32)
        return session["hiper_csrf"]

    @api.before_request
    def local_operator():
        host = (request.host.split(":", 1)[0]).lower()
        if host not in app.config["HIPER_TRUSTED_HOSTS"]:
            return jsonify(error="Host não autorizado para operar o integrador."), 403
        if request.method == "POST" or request.endpoint == "hiper.session_status":
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                return jsonify(error="Origem não autorizada."), 403
            supplied = request.headers.get("X-CSRF-Token", "")
            expected = session.get("hiper_csrf", "")
            if not expected or not secrets.compare_digest(supplied, expected):
                return jsonify(error="Recarregue o painel para confirmar a sessão local.", error_code="csrf_invalid"), 403

    def handled(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except HiperError as error:
                return jsonify(error.payload()), error.http_status
            except ContractError as error:
                return jsonify(error=str(error), error_code="contract_import_failed"), 502
            except KeyError:
                return jsonify(error="Implantação não encontrada.", error_code="deployment_not_found"), 404
            except (TypeError, ValueError):
                return jsonify(error="Requisição inválida.", error_code="invalid_request"), 400
            except Exception:
                return jsonify(error="Operação interrompida. Confira sessão, browser e perfil de seletores.",
                               error_code="hiper_operation_failed", can_resume=True), 503
        return wrapped

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def identifier(data):
        value = data.get("deployment_id")
        if type(value) is not int or value < 1:
            raise ValueError("invalid id")
        return value

    def text(data, key, default=""):
        value = data.get(key, default)
        if not isinstance(value, str) or len(value) > 1000:
            raise ValueError("invalid string")
        return value.strip()

    @api.get("/api/hiper/csrf")
    def csrf_token():
        return jsonify(csrf_token=csrf())

    @api.get("/deployments/<int:deployment_id>/hiper")
    @handled
    def panel(deployment_id):
        return render_template("hiper.html", deployment=service.deployments.get(deployment_id),
                               csrf_token=csrf(), real_enabled=app.config["REAL_HIPER_AUTOMATION_ENABLED"],
                               step_keys=STEP_KEYS)

    @api.get("/api/contracts/<contract_id>")
    @handled
    def contract(contract_id):
        return jsonify(contracts.fetch(contract_id)["data"])

    @api.post("/api/deployments")
    @handled
    def create():
        data = body()
        contract_id = text(data, "contract_id")
        imported = contracts.fetch(contract_id)["data"]
        # Fetch only from configured adapter; clients cannot pretend fixture is API.
        deployment = service.deployments.create(contract_id, imported, source=app.config["CONTRACT_SOURCE"])
        return jsonify(deployment_id=deployment.id, panel_url=f"/deployments/{deployment.id}/hiper"), 201

    @api.get("/api/deployments/<int:deployment_id>")
    @handled
    def status(deployment_id):
        deployment = service.deployments.get(deployment_id)
        public = asdict(deployment)
        public["selected_steps"] = json.loads(public.pop("selected_steps_json"))
        public["steps"] = [asdict(step) for step in service.steps.list_for_deployment(deployment_id)]
        actions = {error.code: error.action for error in (
            HiperError, HiperAuthenticationRequired, HiperSessionExpired, HiperTenantNotResolved,
            HiperStoreNotFound, HiperStoreAmbiguous, HiperStoreIdentityMismatch,
            HiperSelectorNotMapped, HiperSaveFailed, HiperRealModeDisabled,
        )}
        for step in public["steps"]:
            if step["error_code"]:
                step["recommended_action"] = actions.get(step["error_code"], "Revise a evidência e retome após corrigir a causa.")
                step["can_resume"] = True
        public["history"] = [asdict(event) for event in service.deployments.list_audit_events(deployment_id)]
        return jsonify(public)

    @api.post("/api/hiper/session/open")
    @handled
    def open_session():
        data = body()
        return jsonify(runtime.call(service.session(identifier(data), text(data, "domain"), manual=True)))

    @api.get("/api/hiper/session/status")
    @handled
    def session_status():
        deployment_id = request.args.get("deployment_id", type=int)
        if not deployment_id:
            raise ValueError()
        return jsonify(runtime.call(service.session(deployment_id, request.args.get("domain", ""))))

    @api.post("/api/hiper/resolve-store")
    @handled
    def resolve():
        data = body()
        return jsonify(runtime.call(service.resolve(identifier(data), text(data, "domain"), text(data, "selected_store_id"))))

    def run_request(deployment_id, resume=False):
        data = body()
        deployment = service.deployments.get(deployment_id)
        mode = text(data, "mode", deployment.execution_mode if resume else "simulation")
        keys = data.get("steps", json.loads(deployment.selected_steps_json) if resume else ["loja_config"])
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            raise ValueError()
        result = runtime.call(service.start(deployment_id, mode=mode, selected_steps=keys,
                                            confirmed=data.get("confirmed") is True,
                                            operator=text(data, "operator"),
                                            accountant_approved=data.get("accountant_approved") is True, resume=resume))
        return jsonify(result), 202

    @api.post("/api/deployments/<int:deployment_id>/run")
    @handled
    def run(deployment_id):
        return run_request(deployment_id)

    @api.post("/api/deployments/<int:deployment_id>/resume")
    @handled
    def resume(deployment_id):
        return run_request(deployment_id, resume=True)

    @api.post("/api/deployments/<int:deployment_id>/pause")
    @handled
    def pause(deployment_id):
        service.deployments.get(deployment_id)
        service.repo.pause(deployment_id)
        return jsonify(status="pause_requested", message="Pausa solicitada para o próximo limite entre etapas.")

    app.register_blueprint(api)

    @app.after_request
    def private_responses(response):
        if request.path.startswith("/api/") or request.path.endswith("/hiper"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def cleanup():
        if runtime.loop and runtime.thread.is_alive():
            try:
                runtime.call(service.shutdown(), timeout=15)
                runtime.loop.call_soon_threadsafe(runtime.loop.stop)
                runtime.thread.join(timeout=10)
            except Exception:
                pass
    atexit.register(cleanup)
    app.extensions["hiper"]["close"] = cleanup
