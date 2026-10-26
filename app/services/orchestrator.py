"""Sequential, resumable execution of the integrator modules."""

from collections.abc import Callable
from typing import Any
import uuid

from app.automation.base import SelectorsNotCapturedError
from app.automation.modules.clientes import (
    configure_cliente_padrao,
    configure_instituicao_financeira,
)
from app.automation.modules.contadores import configure_contador
from app.automation.modules.loja import configure_loja, configure_vendas
from app.automation.modules.produtos import configure_produto_ncm
from app.automation.modules.usuarios import configure_usuario
from app.models import STEP_KEYS
from app.persistence.repositories import DeploymentRepository, StepRepository
from app.persistence.hiper import HiperRepository
from app.services.validation import validate_for_step
from app.services.users import user_entries, user_error_key


Runner = Callable[[dict[str, Any], bool], str]
RUNNERS: dict[str, Runner] = {
    "cliente_padrao": configure_cliente_padrao,
    "instituicao_financeira": configure_instituicao_financeira,
    "produto_ncm": configure_produto_ncm,
    "contador": configure_contador,
    "loja_config": configure_loja,
    "config_vendas": configure_vendas,
}


class ValidationBlockedError(ValueError):
    pass


class Orchestrator:
    def __init__(self, deployments: DeploymentRepository, steps: StepRepository):
        self.deployments = deployments
        self.steps = steps

    def run(
        self, deployment_id: int, *, dry_run: bool = True,
        user_password: str | None = None,
        user_passwords: list[str] | None = None,
    ) -> None:
        repository = HiperRepository(self.deployments.database_path)
        with repository.lock(f"deployment:{deployment_id}", "legacy:" + uuid.uuid4().hex):
            if dry_run:
                repository.plan(deployment_id, "simulation", list(STEP_KEYS))
            self._run(deployment_id, dry_run=dry_run, user_password=user_password,
                      user_passwords=user_passwords)

    def _run(
        self, deployment_id: int, *, dry_run: bool = True,
        user_password: str | None = None,
        user_passwords: list[str] | None = None,
    ) -> None:
        deployment = self.deployments.get(deployment_id)
        users = user_entries(deployment.data)
        passwords = user_passwords if user_passwords is not None else (
            [user_password] if user_password else []
        )
        if not deployment.approved_at or not deployment.hiper_account:
            raise PermissionError("A conta/loja do Hiper ainda não foi confirmada")
        self.deployments.record_execution_started(
            deployment_id, deployment.approved_by or "operador não informado"
        )
        self.deployments.update_status(deployment_id, "executando")

        for step_key in STEP_KEYS:
            step = self.steps.get(deployment_id, step_key)
            if step.status == "concluida":
                continue
            errors = validate_for_step(deployment.data, step_key)
            if step_key == "usuarios":
                for index in range(len(users)):
                    if index >= len(passwords) or not passwords[index]:
                        errors[user_error_key(index, "senha")] = "Informe a senha para criar o usuário."
                if len(passwords) > len(users):
                    errors["usuarios.senha"] = "Informe uma senha por usuário."
            if errors:
                message = "; ".join(f"{field}: {error}" for field, error in errors.items())
                self.steps.mark_failed(
                    deployment_id, step_key, "VALIDATION_ERROR", message,
                    awaiting_operator=True,
                )
                self.deployments.update_status(deployment_id, "aguardando_intervencao")
                raise ValidationBlockedError(message)

            self.steps.mark_running(deployment_id, step_key)
            try:
                if step_key == "usuarios":
                    results = []
                    for user, password in zip(users, passwords):
                        results.append(configure_usuario(
                            {**deployment.data, "usuarios": user}, password, dry_run,
                        ))
                    evidence = "; ".join(results)
                else:
                    evidence = RUNNERS[step_key](deployment.data, dry_run)
            except SelectorsNotCapturedError as error:
                self.steps.mark_failed(
                    deployment_id, step_key, "SELECTORS_NOT_CAPTURED", str(error),
                    awaiting_operator=True,
                )
                self.deployments.update_status(deployment_id, "aguardando_intervencao")
                raise
            except Exception as error:
                self.steps.mark_failed(
                    deployment_id, step_key, type(error).__name__,
                    "Erro inesperado nesta etapa. Consulte o operador responsável."
                )
                self.deployments.update_status(deployment_id, "falhou")
                raise
            self.steps.mark_completed(deployment_id, step_key, evidence)

        self.deployments.update_status(deployment_id, "homologacao_concluida")
