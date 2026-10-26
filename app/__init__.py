"""Flask application factory for the Hiper integrator."""

import os
import secrets
from itertools import zip_longest
from pathlib import Path
from typing import Any

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from app.automation.base import SelectorsNotCapturedError
from app.api.hiper import register_hiper
from app.config import hiper_config
from app.models import STEP_KEYS
from app.persistence.db import init_db
from app.persistence.repositories import DeploymentRepository, StepRepository
from app.services.contract_adapter import ApiContractAdapter, ContractError, FixtureContractAdapter
from app.services.cnpj_lookup import (
    CnpjNotFoundError, CnpjServiceError, CnpjTimeoutError,
    InvalidCnpjError, lookup_cnpj,
)
from app.services.orchestrator import Orchestrator, ValidationBlockedError
from app.services.card_brands import card_brand_targets
from app.services.users import user_entries, user_error_key
from app.services.validation import FIXED_PRODUCT, USER_PROFILES, validate_sections


FIELD_GROUPS = {
    "company": (
        ("cnpj", "CNPJ"), ("legal_name", "Razão social"),
        ("trade_name", "Nome fantasia"), ("apelido", "Apelido (opcional)"),
        ("logradouro", "Logradouro"), ("bairro", "Bairro"),
        ("municipio", "Cidade"), ("uf", "Estado (UF)"),
        ("postal_code", "CEP"),
        ("inscricao_estadual", "Inscrição estadual (IE)"),
    ),
    "cliente_padrao": (
        ("nome", "Nome"), ("cpf", "CPF"), ("cep", "CEP"),
        ("numero", "Número"),
    ),
    "instituicao_financeira": (
        ("bank_name", "Nome do banco"), ("nome_fantasia", "Nome fantasia"),
        ("cnpj_banco", "CNPJ do banco"), ("cep", "CEP"),
        ("numero", "Número"),
    ),
    "produto_ncm": (
        ("nome", "Nome do Produto"), ("ncm", "NCM"),
        ("codigo_interno", "Código interno do produto"),
        ("unidade_principal", "Unidade de medida principal"),
    ),
    "contador": (("cnpj_contabilidade", "CNPJ da contabilidade"),),
    "fiscal": (
        ("tax_regime", "Regime tributário"), ("csosn", "CSOSN"),
        ("icms_rate", "Alíquota ICMS"),
    ),
    "usuarios": (
        ("nome", "Nome"), ("usuario", "Usuário"),
        ("perfil", "Perfil do usuário"),
    ),
}

REQUIRED_MARKERS = {"instituicao_financeira.cnpj_banco"}
CONFISSAO_DIVIDA = "Tenho ciência da divida no valor de R$ [ValorDocumento]"

SECTION_LABELS = {
    "company": "Empresa", "cliente_padrao": "Cliente padrão",
    "instituicao_financeira": "Instituição financeira",
    "produto_ncm": "Produto padrão", "contador": "Contabilidade",
    "fiscal": "Fiscal",
    "usuarios": "Usuários",
}


def _as_bool(value: Any) -> bool:
    return value is True or str(value).lower() in {"1", "true", "yes", "sim", "on"}


def _prepare_data(data: dict[str, Any]) -> dict[str, Any]:
    """Apply fixed and derived fields before review or persistence."""
    data = dict(data)
    product = {key: value for key, value in FIXED_PRODUCT.items() if key != "ncm"}
    # The legacy fixture contains a sample NCM; never inject it into an API contract.
    product["ncm"] = (data.get("produto_ncm") or {}).get("ncm", "")
    data["produto_ncm"] = product
    company = dict(data.get("company") or {})
    company["isenta_ie"] = _as_bool(company.get("isenta_ie"))
    if company["isenta_ie"]:
        company["inscricao_estadual"] = ""
    data["company"] = company
    fiscal = dict(data.get("fiscal") or {})
    fiscal["busca_automatica_nfe"] = _as_bool(fiscal.get("busca_automatica_nfe"))
    fiscal["cliente_fornecedor"] = (data.get("instituicao_financeira") or {}).get(
        "bank_name", ""
    )
    fiscal["confissao_divida"] = CONFISSAO_DIVIDA
    fiscal["recebimentos"] = {"numero_vias": 1}
    caixas = fiscal.get("caixas") or [{}]
    fiscal["caixas"] = [caixas] if isinstance(caixas, dict) else caixas
    fiscal["nfce"] = dict(fiscal.get("nfce") or {})
    fiscal.setdefault("conta_bancaria", "")
    fiscal["imprimir_nome_fantasia"] = _as_bool(fiscal.get("imprimir_nome_fantasia"))
    data["fiscal"] = fiscal
    cards = dict(data.get("bandeiras_cartao") or {})
    cards.setdefault("credenciadora", "")
    cards["cliente_fornecedor"] = fiscal["cliente_fornecedor"]
    data["bandeiras_cartao"] = cards
    return data


def _form_data(form: Any, existing_data: dict[str, Any]) -> dict[str, Any]:
    data = {
        section: {field: form.get(f"{section}.{field}", "").strip()
                  for field, _ in fields}
        for section, fields in FIELD_GROUPS.items()
        if section != "usuarios"
    }
    data["usuarios"] = [
        dict(zip(("nome", "usuario", "perfil"), values))
        for values in zip_longest(
            *(form.getlist(f"usuarios.{field}") for field in ("nome", "usuario", "perfil")),
            fillvalue="",
        )
    ] or [{}]
    for user in data["usuarios"]:
        for field in user:
            user[field] = user[field].strip()
    data["company"]["isenta_ie"] = form.get("company.isenta_ie") == "yes"
    data["bandeiras_cartao"] = {
        "credenciadora": form.get("bandeiras_cartao.credenciadora", "").strip(),
    }
    data["fiscal"]["busca_automatica_nfe"] = (
        form.get("fiscal.busca_automatica_nfe") == "yes"
    )
    data["fiscal"]["caixas"] = [
        {"numero_caixa": numero.strip(), "serie_fiscal": serie.strip()}
        for numero, serie in zip_longest(
            form.getlist("fiscal.caixas.numero_caixa"),
            form.getlist("fiscal.caixas.serie_fiscal"), fillvalue="",
        )
    ] or [{}]
    data["fiscal"]["nfce"] = {
        "numero_identificacao": form.get("fiscal.nfce.numero_identificacao", "").strip(),
    }
    data["fiscal"]["conta_bancaria"] = form.get("fiscal.conta_bancaria", "").strip()
    data["fiscal"]["imprimir_nome_fantasia"] = form.get("fiscal.imprimir_nome_fantasia") == "yes"
    data["fiscal"]["campos_recebidos"] = (
        (existing_data.get("fiscal") or {}).get("campos_recebidos", {})
    )
    # This legacy field is read-only; preserve the NCM supplied by the contract.
    data["produto_ncm"]["ncm"] = (existing_data.get("produto_ncm") or {}).get("ncm", "")
    for field in ("hiper_domain", "hiper_base_url", "hiper_store_id", "hiper_store_url", "email", "id"):
        if field in existing_data:
            data[field] = existing_data[field]
    return _prepare_data(data)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    project_root = Path(app.root_path).parent
    dry_run = os.getenv("HIPER_DRY_RUN", "true").lower() not in {"0", "false", "no"}
    app.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.getenv("DATABASE_PATH") or str(project_root / "instance" / "integrador.sqlite3"),
        FIXTURES_PATH=str(project_root / "fixtures" / "contracts"),
        DRY_RUN=dry_run,
        CONTRACT_SOURCE=os.getenv(
            "CONTRACT_SOURCE", "api" if os.getenv("CONTRATOS_API_URL") or not dry_run else "fixture"
        ),
        CONTRATOS_API_URL=os.getenv("CONTRATOS_API_URL"),
        CONTRATOS_API_TOKEN=os.getenv("CONTRATOS_API_TOKEN"),
    )
    app.config.update(hiper_config(project_root))
    if os.getenv("CONTRACT_API_URL"):
        app.config.update(CONTRATOS_API_URL=os.getenv("CONTRACT_API_URL"),
                          CONTRATOS_API_TOKEN=os.getenv("CONTRACT_API_TOKEN"),
                          CONTRACT_API_PATH_PREFIX="", CONTRACT_SOURCE=os.getenv("CONTRACT_SOURCE", "api"))
    if test_config:
        app.config.update(test_config)
    init_db(app.config["DATABASE"])

    deployments = DeploymentRepository(app.config["DATABASE"])
    steps = StepRepository(app.config["DATABASE"])
    if app.config["CONTRACT_SOURCE"] == "api":
        contracts = ApiContractAdapter(
            app.config["CONTRATOS_API_URL"], app.config["CONTRATOS_API_TOKEN"],
            path_prefix=app.config.get("CONTRACT_API_PATH_PREFIX", "/api/contratos"),
        )
    elif app.config["CONTRACT_SOURCE"] == "fixture" and app.config["DRY_RUN"]:
        contracts = FixtureContractAdapter(app.config["FIXTURES_PATH"])
    else:
        raise ValueError("CONTRACT_SOURCE deve ser 'api' ou 'fixture' (somente dry-run).")
    orchestrator = Orchestrator(deployments, steps)
    # CSC values are kept in this process only, never in SQLite or browser cookies.
    nfce_tokens: dict[int, str] = {}
    app.extensions["nfce_tokens"] = nfce_tokens
    register_hiper(app, contracts)

    @app.get("/")
    def index():
        return render_template("index.html", deployments=deployments.list_all())

    @app.get("/api/cnpj")
    def consult_cnpj():
        try:
            company = lookup_cnpj(request.args.get("cnpj", ""))
        except InvalidCnpjError as error:
            return jsonify({"error": str(error)}), 400
        except CnpjNotFoundError as error:
            return jsonify({"error": str(error)}), 404
        except CnpjTimeoutError as error:
            return jsonify({"error": str(error)}), 504
        except CnpjServiceError as error:
            return jsonify({"error": str(error)}), 502
        return jsonify(company)

    @app.post("/deployments/import")
    def import_contract():
        contract_id = request.form.get("contract_id", "").strip()
        try:
            contract = contracts.fetch(contract_id)
            data = contract["data"]
            secrets = contract["secrets"]
            fiscal = data.setdefault("fiscal", {})
            fiscal["conta_bancaria"] = ""
            nfce_token = secrets.get("csc")
            fiscal["campos_recebidos"] = {
                "arquivo": bool(
                    secrets.get("certificado_arquivo_ref")
                    or secrets.get("certificado_digital")
                    or secrets.get("certificado_arquivo")
                    or secrets.get("certificado_base64")
                    or secrets.get("certificado")
                    or secrets.get("certificado_pfx")
                    or secrets.get("certificado_p12")
                ),
                "credencial": bool(secrets.get("certificado_senha")),
                "codigo": bool(secrets.get("csc")),
            }
            del secrets
            del contract
        except ContractError as error:
            flash(str(error), "error")
            return redirect(url_for("index"))
        data = _prepare_data(data)
        deployment = deployments.create(contract_id, data, source=app.config["CONTRACT_SOURCE"])
        if nfce_token:
            nfce_tokens[deployment.id] = nfce_token
        flash("Contrato importado. Revise e complete os dados.", "success")
        return redirect(url_for("review_deployment", deployment_id=deployment.id))

    @app.route("/deployments/<int:deployment_id>/review", methods=["GET", "POST"])
    def review_deployment(deployment_id: int):
        deployment = deployments.get(deployment_id)
        data = _prepare_data(deployment.data)
        errors: dict[str, str] = {}
        if request.method == "POST":
            nfce_token = request.form.get("fiscal.nfce.token", "").strip()
            if nfce_token:
                nfce_tokens[deployment_id] = nfce_token
            data = _form_data(request.form, deployment.data)
            errors = validate_sections(data)
            if not errors:
                deployments.update_review(deployment_id, data)
                flash("Dados validados. Confirme a conta antes da execução.", "success")
                return redirect(url_for("execute_deployment", deployment_id=deployment_id))
            flash("Corrija os campos indicados.", "error")
        return render_template(
            "review.html", deployment=deployment, data=data, errors=errors,
            field_groups=FIELD_GROUPS, section_labels=SECTION_LABELS,
            required_markers=REQUIRED_MARKERS, user_profiles=USER_PROFILES,
            users=user_entries(data), user_error_key=user_error_key,
            card_targets=card_brand_targets(data),
            nfce_token_available=deployment_id in nfce_tokens,
            secret_status={
                key: (
                    "Recebido do contrato" if data.get("fiscal", {}).get(
                        "campos_recebidos", {}
                    ).get(key) else "Não informado no contrato"
                ) if key in data.get("fiscal", {}).get("campos_recebidos", {})
                else "Disponibilidade desconhecida"
                for key in ("arquivo", "credencial", "codigo")
            },
        )

    @app.route("/deployments/<int:deployment_id>/execute", methods=["GET", "POST"])
    def execute_deployment(deployment_id: int):
        deployment = deployments.get(deployment_id)
        deployment_steps = steps.list_for_deployment(deployment_id)
        users_pending = steps.get(deployment_id, "usuarios").status != "concluida"
        users = user_entries(deployment.data)
        if request.method == "POST":
            if not app.config["DRY_RUN"]:
                flash("Use o painel Hiper para verificar a filial e confirmar a execução real.", "error")
                return redirect(url_for("hiper.panel", deployment_id=deployment_id))
            account = request.form.get("hiper_account", "").strip()
            operator = request.form.get("approved_by", "").strip()
            confirmed = request.form.get("account_confirmed") == "yes"
            user_passwords = request.form.getlist("usuarios.senha")
            if not account or not operator or not confirmed:
                flash("Informe conta, operador e confirme explicitamente a loja.", "error")
            elif users_pending and (
                len(user_passwords) != len(users) or not all(user_passwords)
            ):
                flash("Informe a senha do usuário em cada bloco para iniciar a configuração.", "error")
            else:
                deployments.confirm_account(deployment_id, account, operator)
                try:
                    orchestrator.run(
                        deployment_id, dry_run=app.config["DRY_RUN"],
                        user_passwords=user_passwords,
                    )
                    flash(f"As {len(STEP_KEYS)} etapas foram concluídas.", "success")
                except (SelectorsNotCapturedError, ValidationBlockedError) as error:
                    flash(f"Execução interrompida: {error}", "error")
                except Exception:
                    flash("Execução interrompida por erro inesperado. Consulte o relatório.", "error")
                finally:
                    user_passwords.clear()
                return redirect(url_for("deployment_report", deployment_id=deployment_id))
        return render_template(
            "execute.html", deployment=deployment, steps=deployment_steps,
            dry_run=app.config["DRY_RUN"], users_pending=users_pending,
            users=users,
        )

    @app.get("/deployments/<int:deployment_id>/report")
    def deployment_report(deployment_id: int):
        return render_template(
            "report.html", deployment=deployments.get(deployment_id),
            steps=steps.list_for_deployment(deployment_id),
            audit_events=deployments.list_audit_events(deployment_id),
        )

    @app.errorhandler(KeyError)
    def not_found(_: KeyError):
        return render_template("404.html"), 404

    return app
