"""Domain models and workflow constants."""

from dataclasses import dataclass
from typing import Any


STEP_KEYS = (
    "cliente_padrao",
    "instituicao_financeira",
    "produto_ncm",
    "contador",
    "loja_config",
    "config_vendas",
    "usuarios",
)

DEPLOYMENT_STATUSES = (
    "rascunho",
    "validado",
    "aguardando_confirmacao_conta",
    "executando",
    "aguardando_intervencao",
    "falhou",
    "homologacao_concluida",
    "aguardando_aprovacao",
    "producao_confirmada",
)

STEP_STATUSES = (
    "pendente",
    "executando",
    "concluida",
    "ignorada_justificadamente",
    "falhou",
    "aguardando_operador",
)


@dataclass(frozen=True)
class Deployment:
    id: int
    contract_id: str
    hiper_account: str | None
    environment: str
    status: str
    data: dict[str, Any]
    created_at: str
    updated_at: str
    approved_by: str | None
    approved_at: str | None
    hiper_base_url: str | None = None
    hiper_store_id: str | None = None
    hiper_store_name: str | None = None
    hiper_store_cnpj: str | None = None
    hiper_store_url: str | None = None
    store_resolution_method: str | None = None
    store_verified_at: str | None = None
    execution_mode: str = "simulation"
    selected_steps_json: str = '["loja_config"]'
    pause_requested: int = 0
    contract_source: str = "fixture"


@dataclass(frozen=True)
class DeploymentStep:
    id: int
    deployment_id: int
    step_key: str
    status: str
    attempts: int
    started_at: str | None
    finished_at: str | None
    evidence_reference: str | None
    error_code: str | None
    error_message_sanitized: str | None
    execution_mode: str = "simulation"


@dataclass(frozen=True)
class AuditEvent:
    id: int
    deployment_id: int
    action: str
    actor: str
    occurred_at: str
