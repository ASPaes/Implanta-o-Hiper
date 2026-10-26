# Validação local — 08/10/2026

## Resultado

Python 3.14 no Windows, Flask 3.1.3 e Playwright 1.63.0. Dependências instaladas
em `.venv`; Chromium instalado pelo Playwright. Chrome local também disponível.

```powershell
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -q
# 117 passed in 67.08s
.\.venv\Scripts\python.exe -m pip check
# No broken requirements found.
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
# exit 0
git -c core.whitespace=cr-at-eol -c core.safecrlf=false diff --check
# exit 0
```

Sem `RUN_BROWSER_TESTS=1`, os três testes antigos de Chrome são opcionais.
Os testes novos de Chromium são executados normalmente.

Servidor local iniciado com `run.py`, modo real desabilitado, escutando em
`http://127.0.0.1:5000`. GET `/` respondeu 200; GET `/api/contracts/1042`
retornou a empresa e o CNPJ da fixture. Não foram realizadas alterações em Hiper.

## Cobertura observada

- CNPJ e resolução de domínio, URL e ID; tenant conflitante recusado.
- Filial única, ausente, ambígua, seleção manual e CNPJ divergente.
- Migração de schema antigo sem perda; locks, owner, expiração e revisão bloqueada.
- Payloads de API moderno e legado; NCM fornecido preservado, ausência não inventada.
- CSRF, host/origem, gate real e impossibilidade de promover fixture para real.
- Login/sessão controlada, persistência/reutilização e expiração detectada.
- Dados gerais: dry-run sem fill/save, gravação real no servidor HTML local,
  releitura após reload, segunda execução sem save, save não persistido recusado.
- Etapas não mapeadas bloqueadas; retomada preserva prefixo concluído do mesmo modo.
- Troca dry-run → real não herda sucesso simulado; pausa entre etapas.
- Evidência autenticada com campos mascarados; login sem screenshot.
- Painel no browser: importar, executar, retomar, progresso e largura móvel.
- Formulários e testes anteriores, incluindo os três testes opcionais de Chrome.

## Arquivos principais

Novos: `app/config.py`, `app/api/hiper.py`,
`app/services/hiper_deployment.py`, `app/persistence/hiper.py`,
`app/automation/hiper/{auth,browser,errors,evidence,navigation,resolver,selectors,steps}.py`,
`app/templates/hiper.html`, `app/static/hiper.js`, `scripts/inspect_hiper.py`,
`tests/test_hiper_{api,browser,repository,resolver,service,ui}.py`, fixtures locais
e documentação de arquitetura/plano/perfil.

Atualizados: factory, modelos, schema/repositories, adapter de contratos,
orquestrador legado, validação, sanitização, templates de lista/execução/relatório,
CSS, README, `.env.example` e `.gitignore`.
README anterior preservado em `docs/legacy-mvp.md`.

## Limite de aceite

Infraestrutura e motor de dados gerais verificados localmente. Login real,
descoberta e save no Hiper ainda dependem de acesso autorizado e perfil capturado.
Não há evidência de funcionamento no Hiper de produção. Nenhum seletor do teste
foi apresentado como seletor de produção. Usuários e telas fiscais permanecem
explicitamente não automatizados em modo real; lista paginada requer extensão.
