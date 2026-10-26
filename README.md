# Integrador Hiper Gestão

Importa contratos, permite revisão pelo operador e configura uma filial Hiper
via Playwright, validando CNPJ e registrando etapas e auditoria em SQLite.
Evolui a base existente em **Flask/Jinja**; preserva os formulários e o banco.

## O que está implementado

- Importação por fixture, API legada e API de contratos com payload plano.
- Revisão existente com múltiplos usuários/caixas, dados fiscais e bandeiras.
- API JSON e painel Hiper com sessão, descoberta de filial, modos e progresso.
- Chromium assíncrono, login manual, storage separado por tenant e expiração.
- Resolver híbrido de domínio/URL/ID/CNPJ e seleção explícita em ambiguidade.
- Migração SQLite sem apagar dados, cache de filial, auditoria e locks com lease.
- Pausa entre etapas, retomada e separação entre resultados simulados e reais.
- Etapa **dados gerais da loja** (`loja_config`): comparar, alterar somente
  campos não fiscais mapeados, salvar, recarregar e verificar; execução repetida
  não salva se os valores já coincidirem.
- Inspeção local e screenshots de falha com campos mascarados.

**Situação da automação:** dados gerais foi executado e verificado com Chromium
em páginas HTML locais controladas. Nenhuma conta real do Hiper foi acessada.
Os seletores de produção precisam ser capturados em sessão autorizada.
Sem perfil, o sistema bloqueia com `selector_not_mapped`.

## Instalar e iniciar

Python 3.10+ no Windows; recomendado 3.12+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
$env:CONTRACT_SOURCE = 'fixture'
.\.venv\Scripts\python.exe run.py
```

Abra **http://127.0.0.1:5000**. Importe `1042`, revise os dados e abra o link
**Hiper**. O formulário anterior continua disponível para simulação das sete
etapas, sem navegador. Fixture é fictícia e bloqueada em modo real.
Banco: `instance/integrador.sqlite3`; configure `DATABASE_PATH` se necessário.

## Configuração

`.env.example` documenta as variáveis; o processo **não carrega `.env`
automaticamente**. Defina-as no ambiente do PowerShell/serviço.

```powershell
$env:FLASK_SECRET_KEY = 'chave-aleatoria-longa-especifica-desta-instalacao'
$env:CONTRACT_SOURCE = 'api'
$env:CONTRACT_API_URL = 'https://seu-sistema/contratos'
$env:CONTRACT_API_TOKEN = 'token-configurado-no-servidor'
$env:HIPER_SELECTOR_PROFILE = 'C:\config-integrador\hiper-profile.json'
$env:HIPER_BROWSER_HEADLESS = 'false'
$env:REAL_HIPER_AUTOMATION_ENABLED = 'false'
.\.venv\Scripts\python.exe run.py
```

API moderna: `GET {CONTRACT_API_URL}/{id}` com Bearer, aceitando
`id`, `company` (string), `cnpj`, `email`, `cep`, `users`, `logo_url` e campos
opcionais `hiper_domain`, `hiper_base_url`, `hiper_store_id`, `hiper_store_url`.
Login e perfil de usuários precisam ser complementados quando ausentes.
API legada: `CONTRATOS_API_URL`/`CONTRATOS_API_TOKEN`, endpoint
`/api/contratos/{id}`, com seções da fixture; continua compatível.
A URL moderna tem precedência quando configurada. Tokens não vão ao frontend.

`HIPER_STORAGE_STATE_DIR`, `HIPER_SCREENSHOT_DIR`, `HIPER_BROWSER_TIMEOUT_MS`,
`HIPER_DEFAULT_DOMAIN`, `HIPER_DEBUG` e `HIPER_TRUSTED_HOSTS` são opcionais.
Segredos ficam no ambiente/memória, fora do Git e SQLite; estado autenticado
e artefatos usam diretórios privados (ACL no Windows, modo 0700 no Unix).
Execute como usuário com acesso restrito a esses diretórios. Não use Flask debug
em operação real: o reloader cria processos e interrompe sessões/tarefas.

## Primeiro login e mapeamento autorizado

1. Informe o tenant no painel (ex.: `seucliente.hiper.com.br`).
2. Clique **Abrir Hiper para autenticar**; Chromium abre visível.
3. Faça login manual e conclua MFA/CAPTCHA no próprio navegador.
4. Clique **Verificar sessão**. O marcador autenticado deve existir no perfil;
   estado só é salvo após confirmar tenant e sessão válida.
5. Clique **Localizar filial**. O CNPJ encontra a filial; duplicatas exigem
   seleção manual. O CNPJ é relido na tela de dados gerais.
6. Confira nome, CNPJ encontrado, domínio, ID da filial e ambiente no painel.

Para capturar seletores de produção:

```powershell
.\.venv\Scripts\python.exe scripts/inspect_hiper.py --domain SEU_TENANT --snapshot
.\.venv\Scripts\python.exe scripts/inspect_hiper.py --domain SEU_TENANT --profile C:\config-integrador\hiper-profile.json --debug
```

Sem perfil, a inspeção exporta metadados permitidos, sem screenshot de login nem
storage. [Esquema e procedimento do perfil](docs/selector-profile.md).
O perfil em `tests/fixtures/` pertence exclusivamente ao servidor HTML de teste.

## Executar

| Modo no painel | Comportamento |
|---|---|
| Simulação | Sem browser; resultado explicitamente simulado nas etapas selecionadas |
| Dry-run | Browser autorizado; lê identidade/campos e informa diferenças; não preenche nem salva |
| Real | Salva após gates e confirmação, verificando persistência por releitura |

Comece com **dados gerais da loja** selecionado. Para real, configure
`REAL_HIPER_AUTOMATION_ENABLED=true`, reinicie, importe contrato da API, valide
a filial, informe operador e marque a autorização explícita.
Nenhuma URL/UUID de cliente está embutida. CNPJ divergente bloqueia imediatamente;
nome/URL/ID não substituem CNPJ.

**Pausa** termina a operação corrente e para entre etapas. **Retomar** revalida
a filial e continua nas etapas interrompidas; concluídos do mesmo modo são
preservados. **Executar** novamente reinspeciona os valores e não repete save
quando já coincidem. Após expiração, faça login
e verifique a sessão antes de retomar. Execução concorrente no mesmo tenant/filial
recebe HTTP 409. Após queda do processo, locks expiram em até 120s;
retomada não presume que o último save foi concluído.

Concluído refere-se às etapas **selecionadas**, não à implantação integral da
conta. Relatório mostra estados, tentativas, modos, erros, evidências e histórico.

## Etapas e limites

`loja_config` automatiza dados gerais não fiscais e somente campos do perfil.
Não altera CNPJ, razão social legal, IE ou tributação. Usuários, cliente padrão,
banco, produto/NCM, contador e vendas/cartões possuem simulação; **automação real
ainda não mapeada**, retornando `selector_not_mapped`.
Tributação, séries, NFC-e/CSC, A1/A3, caixas e frente de caixa não possuem runner
real. Exigem levantamento e testes específicos.

Valores fiscais devem vir do contrato/contabilidade e exigir aprovação
`accountant_approved=true` quando suportados. O formulário legado conserva os
campos não fiscais do produto padrão. Seu NCM vem do contrato e permanece somente
leitura; NCM ausente não é inventado. A fixture contém um exemplo para simulação.
Não há endpoint de upload A1 nesta versão. O utilitário legado baixa certificado
temporário e remove ao finalizar; o novo runner não usa certificado/senha.
A3 não é tratado como A1. CSC legado fica na memória e desaparece após reiniciar.
Senhas de usuários são usadas somente pela simulação legada, sem persistência.
Evidências não exportam cookies, storage, valores de formulário ou HTML bruto.

Lista de lojas paginada/virtualizada exige suporte adicional; o perfil deve
indicar uma lista completa carregada. Perfil depende de revisão humana
autorizada. Mudanças na UI podem interromper execução.
Opera localmente com loop async interno, sem fila externa. Para rede, use
autenticação/TLS no proxy e host configurado; não é serviço multiusuário.
Não exponha `run.py` diretamente na internet.

## API operacional

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/hiper/csrf` | Token da sessão local, separado do token da API de contratos |
| GET | `/api/contracts/{id}` | Dados normalizados sem segredos |
| POST | `/api/deployments` | Importar `{ "contract_id": "1042" }` |
| GET | `/api/deployments/{id}` | Contexto, etapas, modos e histórico |
| POST | `/api/hiper/session/open` | `{ "deployment_id": 1, "domain": "seucliente" }` |
| GET | `/api/hiper/session/status?deployment_id=1&domain=seucliente` | Confirmar e salvar sessão |
| POST | `/api/hiper/resolve-store` | deployment/domain e opcional `selected_store_id` |
| POST | `/api/deployments/{id}/run` | `mode`, `steps`, `operator`, `confirmed` |
| POST | `/api/deployments/{id}/resume` | Mesmo formato; modo/plano anterior se omitidos |
| POST | `/api/deployments/{id}/pause` | Pausa cooperativa |

POSTs e verificação de sessão exigem cookie local e `X-CSRF-Token`, obtido no
painel ou `/api/hiper/csrf`. Execução retorna 202; consulte status até terminar.
Erros informam código, causa, ação e retomada. Contrato de API deve ser importado
pelo adapter do servidor; cliente HTTP não pode promover fixture para produção.

## Testes e arquitetura

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# Testes opcionais antigos com Chrome instalado:
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_cnpj_browser.py -q
```

Novos testes de browser executam por padrão com Chromium instalado e páginas
locais; não dependem de conta real. Cobrem gravação/reload, idempotência, dry-run,
identidade, sessão persistida/expirada, falhas e evidências. Testes reais no Hiper
devem ser manuais e em cliente/ambiente autorizado.

[Arquitetura e estratégias A/B/C/D](docs/architecture.md) ·
[Plano](docs/superpowers/plans/2026-10-08-integrador-hiper.md) ·
[Documentação histórica do MVP](docs/legacy-mvp.md).
