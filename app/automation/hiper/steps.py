"""Idempotent, verified non-fiscal general store data."""

from dataclasses import dataclass

from app.automation.hiper.errors import HiperError, HiperSaveFailed, HiperSelectorNotMapped
from app.automation.hiper.resolver import verify_identity


@dataclass
class StepResult:
    status: str
    message: str


class DeploymentStep:
    name: str

    async def inspect(self):
        raise NotImplementedError

    def validate(self, desired: dict):
        raise NotImplementedError

    async def execute(self, changes: dict):
        raise NotImplementedError

    async def verify(self, desired: dict):
        raise NotImplementedError


class DadosLojaStep(DeploymentStep):
    name = "loja_config"
    # Fiscal fields and CNPJ can NEVER be written by this step.
    allowed = {"trade_name", "apelido", "email", "postal_code", "logradouro", "bairro", "municipio", "uf"}

    def __init__(self, navigation, store, company: dict, *, guard=None):
        self.navigation, self.store, self.company = navigation, store, company
        self.profile, self.page = navigation.profile, navigation.page
        self.spec = self.profile.require("general_data")
        self.guard = guard or (lambda: None)

    def desired(self) -> dict:
        fields = self.spec.get("fields", {})
        if not fields or not set(fields).issubset(self.allowed):
            raise HiperSelectorNotMapped("Mapeie somente campos não fiscais de dados gerais.")
        # Missing values are not guessed and do not clear existing Hiper values.
        return {key: str(self.company[key]).strip() for key in fields
                if self.company.get(key) is not None and str(self.company[key]).strip()}

    def validate(self, desired: dict):
        if not desired:
            raise HiperError("Contrato não contém valores para os campos mapeados de dados gerais.")
        verify_identity(self.company["cnpj"], self.store.cnpj)

    async def inspect(self) -> dict:
        await self.navigation.general(self.store)
        await self.navigation.identity(self.company["cnpj"])
        return {key: await self.profile.read(self.page, spec)
                for key, spec in self.spec["fields"].items()}

    async def execute(self, changes: dict):
        self.guard()
        await self.navigation.identity(self.company["cnpj"])
        # Resolve every locator BEFORE filling anything.
        fields = {key: await self.profile.unique(self.page, self.spec["fields"][key]) for key in changes}
        save = await self.profile.unique(self.page, self.spec["save"])
        for key, locator in fields.items():
            await locator.fill(changes[key])
        self.guard()
        await self.navigation.identity(self.company["cnpj"])
        await save.click()
        # Captured success marker is required, then verify persistence after reload.
        await self.profile.unique(self.page, self.spec["saved"])

    async def verify(self, desired: dict):
        await self.page.reload(wait_until="domcontentloaded")
        await self.navigation.identity(self.company["cnpj"])
        for key, value in desired.items():
            actual = await self.profile.read(self.page, self.spec["fields"][key])
            if actual != value:
                raise HiperSaveFailed(f"Valor salvo não coincide com o desejado: {key}.")

    async def run(self, mode: str) -> StepResult:
        desired = self.desired()
        self.validate(desired)
        if mode == "real":
            self.profile.require("general_data")
            if not self.spec.get("save") or not self.spec.get("saved"):
                raise HiperSelectorNotMapped("Mapeie salvar e confirmação de gravação.")
        current = await self.inspect()
        changes = {key: value for key, value in desired.items() if current[key] != value}
        if not changes:
            return StepResult("skipped", "Valores existentes conferidos; nenhuma alteração necessária.")
        if mode == "dry_run":
            return StepResult("success", "dry-run: alterar somente " + ", ".join(changes) + "; nenhuma escrita realizada.")
        if mode != "real":
            raise HiperError("Modo de execução inválido para o navegador.")
        await self.execute(changes)
        await self.verify(desired)
        return StepResult("success", "Gravação confirmada após recarregar: " + ", ".join(changes) + ".")
