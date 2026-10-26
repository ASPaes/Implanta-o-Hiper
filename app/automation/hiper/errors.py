"""Stable operator-facing failures; never expose raw Playwright exceptions."""


class HiperError(RuntimeError):
    code = "hiper_validation_failed"
    status = "waiting_user"
    http_status = 422
    action = "Revise os dados e retome a implantação."

    def __init__(self, message: str, *, candidates: list | None = None):
        super().__init__(message)
        self.candidates = candidates or []

    def payload(self) -> dict:
        return {"error_code": self.code, "error": str(self), "action": self.action,
                "can_resume": True, "status": self.status, "candidates": self.candidates}


class HiperAuthenticationRequired(HiperError):
    code = "authentication_required"
    status = "awaiting_auth"
    http_status = 401
    action = "Abra o Hiper, conclua o login manual e verifique a sessão."


class HiperSessionExpired(HiperAuthenticationRequired):
    code = "session_expired"


class HiperTenantNotResolved(HiperError):
    code = "tenant_not_resolved"
    action = "Informe um domínio HTTPS do Hiper e confira as URLs do contrato."


class HiperStoreNotFound(HiperError):
    code = "store_not_found"
    http_status = 404
    action = "Confira o CNPJ e as filiais acessíveis nesta conta."


class HiperStoreAmbiguous(HiperError):
    code = "store_ambiguous"
    http_status = 409
    action = "Selecione explicitamente uma das filiais encontradas."


class HiperStoreIdentityMismatch(HiperError):
    code = "store_identity_mismatch"
    status = "blocked"
    action = "Interrompido: selecione a filial cujo CNPJ coincide com o contrato."


class HiperSelectorNotMapped(HiperError):
    code = "selector_not_mapped"
    status = "blocked"
    action = "Inspecione a sessão autorizada e configure o perfil de seletores."


class HiperSaveFailed(HiperError):
    code = "save_failed"
    status = "failed"
    action = "Confira a evidência e os valores salvos antes de retomar."


class HiperDeploymentAlreadyRunning(HiperError):
    code = "deployment_already_running"
    http_status = 409
    action = "Aguarde a execução ativa deste tenant/filial terminar."


class HiperRealModeDisabled(HiperError):
    code = "real_mode_disabled"
    status = "blocked"
    http_status = 403
    action = "Habilite a flag do servidor, use contrato de API e confirme a escrita."
