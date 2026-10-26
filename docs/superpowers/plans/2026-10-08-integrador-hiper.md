# Integrador Hiper Implementation Plan

**Goal:** evoluir a base existente para integração assíncrona segura e testável.
**Architecture:** manter Flask/Jinja e repositories SQLite. Isolar Playwright em
adapter async; usar perfis de seletores capturados e identidade por CNPJ.
**Tech Stack:** Python, Flask, SQLite, HTTPX, Playwright, pytest.

Execução inline no worktree já isolado; sem commits automáticos.

## Task 1: configuração e contrato
**File:** `app/config.py`, `app/services/contract_adapter.py`.
**Test:** importar payload plano e seções legadas; preservar campos opcionais.
**Implementation:** `company = raw['company'] if isinstance(raw.get('company'), dict) else {'legal_name': raw.get('company', ''), 'cnpj': raw.get('cnpj', ''), 'postal_code': raw.get('cep', '')}`. URL API moderna usa `/{id}`; legada mantém `/api/contratos/{id}`. Flags reais default false.
**Verification:** `.venv/Scripts/python -m pytest tests/test_contract_adapter.py tests/test_hiper_resolver.py`.
**Commit:** `feat(contracts): support flat contracts and dynamic tenant hints` (não executar automaticamente).

## Task 2: migrations e locks
**File:** `app/persistence/db.py`, `app/persistence/hiper.py`, `app/models.py`.
**Test:** banco antigo migra sem perda; duas aquisições concorrentes recebem conflito.
**Implementation:** `INSERT INTO hiper_locks(resource, owner, expires_at) VALUES (?, ?, ?)` dentro de transação; renovar/release apenas pelo owner. Contexto persistido em colunas próprias, mapping separado.
**Verification:** `.venv/Scripts/python -m pytest tests/test_repositories.py tests/test_hiper_repository.py`.
**Commit:** `feat(persistence): persist store identity and leased execution locks`.

## Task 3: resolução e seletores
**File:** `app/automation/hiper/resolver.py`, `selectors.py`, `navigation.py`, `errors.py`.
**Test:** domínios/URLs conflitantes, CNPJ divergente, duplicatas e seleção manual.
**Implementation:** `matches = [store for store in stores if normalize_cnpj(store.cnpj) == normalize_cnpj(contract_cnpj)]`; mais de uma exige ID manual. Locators sempre únicos. Perfil vazio levanta `selector_not_mapped`.
**Verification:** `.venv/Scripts/python -m pytest tests/test_hiper_resolver.py`.
**Commit:** `feat(hiper): resolve tenants and verify store identity`.

## Task 4: sessão e inspeção
**File:** `app/automation/hiper/browser.py`, `auth.py`, `evidence.py`, `scripts/inspect_hiper.py`.
**Test:** storage por tenant, reutilização e expiração; snapshot exclui valores/segredos.
**Implementation:** `context = await browser.new_context(storage_state=str(state) if state.exists() else None)`; salvar apenas após marcador autenticado. Abrir login headed e reutilizar objetos no loop dedicado.
**Verification:** `.venv/Scripts/python -m pytest tests/test_hiper_browser.py`.
**Commit:** `feat(hiper): persist authorized browser sessions and sanitized evidence`.

## Task 5: etapa verificável
**File:** `app/automation/hiper/steps.py`.
**Test:** dry-run sem escrita, save+reload confirmado, segunda execução sem save, save falho, identidade trocada.
**Implementation:** `changes = {key: value for key, value in desired.items() if current[key] != value}`; validar CNPJ antes de fill e antes de save; após reload, conferir todos os campos desejados.
**Verification:** `.venv/Scripts/python -m pytest tests/test_hiper_browser.py`.
**Commit:** `feat(hiper): implement verified idempotent general store data`.

## Task 6: serviço e endpoints
**File:** `app/services/hiper_deployment.py`, `app/api/hiper.py`, `app/__init__.py`.
**Test:** gate real, fixture bloqueada, locks 409, pause/resume, separação modos, erros claros e CSRF.
**Implementation:** agendar coroutine e retornar 202; estados e erros persistidos; consulta retorna contexto, etapas e auditoria; resultado real nunca herdado da simulação.
**Verification:** `.venv/Scripts/python -m pytest tests/test_hiper_api.py tests/test_hiper_service.py`.
**Commit:** `feat(deployments): add asynchronous execution and resumption API`.

## Task 7: painel operacional
**File:** `app/templates/hiper.html`, `app/static/hiper.js`, `app/templates/execute.html`.
**Test:** fluxo de importação, painel, erros acessíveis, status e filial sem injeção HTML.
**Implementation:** formulário domínio/sessão/filial, modos, operador e confirmações; polling com `textContent`; pausa e retomada sem reload destrutivo.
**Verification:** browser local e testes API/UI.
**Commit:** `feat(ui): expose sessions and deployment progress`.

## Task 8: documentação e aceitação
**File:** `README.md`, `.env.example`, `.gitignore`, `docs/selector-profile.md`.
**Test:** suíte completa e Chromium local, smoke HTTP, compileall, diff whitespace.
**Implementation:** instruções de login manual, modos, perfil, endpoints e limite de produção explícito.
**Verification:** `.venv/Scripts/python -m pytest`; `git diff --check`.
**Commit:** `docs(hiper): document setup and verified automation coverage`.
