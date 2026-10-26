# Integrador Hiper Gestão — Brief para implementação (Fase 1)

**Leia isto por completo antes de escrever qualquer código.** Este arquivo é a
especificação da Fase 1 (MVP). Não implemente nada fora do escopo descrito
aqui sem perguntar antes.

## 1. O que é o sistema

Uma ponte entre um sistema interno de execução de contratos e o Hiper
Gestão. Fluxo: **sistema de contratos → tela de revisão (ver/editar/
completar) → configuração automatizada dentro do Hiper → relatório**.

O Hiper não tem API, então a configuração é feita com Playwright
controlando um navegador real.

## 2. Divisão de responsabilidade entre pessoa e robô — IMPORTANTE

Isto muda o desenho do login em relação a qualquer versão anterior deste
projeto que você encontrar:

- **O operador (pessoa) faz manualmente:** a criação da conta no Hiper e o
  login (usuário/senha, MFA se houver).
- **O robô nunca faz login nem cadastro de conta.** Ele só entra em ação
  **depois** que o operador já está autenticado dentro do Hiper, e a
  partir daí executa apenas telas de **configuração**.
- Portanto o robô deve **conectar-se a uma sessão de navegador já aberta e
  já logada**, não abrir uma sessão nova. Duas formas aceitáveis:
  1. **Perfil persistente:** o robô abre o navegador com
     `browser_type.launch_persistent_context(user_data_dir, headless=False)`
     e o operador faz o cadastro/login nessa mesma janela antes de clicar em
     "Iniciar configuração" no integrador. É a forma recomendada para
     começar.
  2. **Conectar a um Chrome já aberto:** o operador sobe o Chrome com
     `--remote-debugging-port=9222`, faz login manualmente, e o robô se
     conecta com `playwright.chromium.connect_over_cdp("http://localhost:9222")`.
     Alternativa para quando o operador já tem rotina própria de abrir o
     Hiper.
- Antes de rodar qualquer etapa, o integrador deve mostrar ao operador uma
  confirmação do tipo "esta é a conta/loja correta para este contrato?" e só
  seguir após confirmação explícita.

## 3. Escopo desta fase

**Construir:**
- Importação de contrato (adaptador com fixture local; interface pronta
  para trocar por chamada HTTP real depois).
- Tela de revisão/edição/complemento dos dados, com validação de
  obrigatórios.
- Orquestrador que executa os módulos abaixo em sequência, registra estado
  por etapa e permite retomar sem duplicar o que já foi confirmado.
- Persistência simples (SQLite, duas tabelas: implantações e etapas).
- Módulos de automação em **modo dry-run funcional** (simula sucesso sem
  abrir navegador) e **modo real bloqueado** até os seletores serem
  capturados (ver Seção 7).
- Relatório final por implantação.

**Não construir nesta fase:** fila/worker separado, automação de
login/MFA/CAPTCHA, automação da troca de ambiente para produção
(homologação → produção continua manual e só é *registrada*, nunca
executada pelo robô), criação de conta no Hiper.

## 4. Módulos e ordem de execução

Esta é a ordem confirmada pelo usuário, com as dependências entre módulos.
Cada módulo é uma etapa própria no orquestrador (`step_key`).

| # | step_key | Onde no Hiper | Ação do robô | Depende de |
|---|---|---|---|---|
| 1 | `cliente_padrao` | Cadastros → Clientes | Localizar ou cadastrar cliente padrão (pessoa física) | — |
| 2 | `instituicao_financeira` | Cadastros → Clientes | Localizar ou cadastrar o banco (pessoa jurídica) | — |
| 3 | `produto_ncm` | Cadastros → Produtos | Abrir o produto padrão e adicionar/editar o NCM | NCM validado pela contabilidade |
| 4 | `contador` | Contabilidade → Contadores | Adicionar o CNPJ da contabilidade | CNPJ informado (origem a confirmar — Seção 9) |
| 5 | `loja_config` | Configurações → Minhas Lojas | Entrar na loja e ajustar os registros necessários (dados gerais, tributação, cupom fiscal conforme aplicável) | Dados fiscais validados |
| 6 | `config_vendas` | Configurações de Vendas | Vincular o cliente padrão e ajustar o necessário | Etapa 1 |

> **Assunção a confirmar com o usuário antes de implementar o real do passo
> 1/2:** os cadastros de pessoa física (cliente) e pessoa jurídica (banco)
> acontecem dentro de **Cadastros → Clientes**, não em uma tela separada de
> "Usuários". Se isso estiver errado, ajuste `step_key` e o módulo de
> automação correspondente antes de gravar os seletores.

Módulos citados na documentação original (produtos além do NCM, usuários e
perfis de acesso do sistema, opções de venda/Pix, bandeiras de cartão,
certificado digital, caixas/séries fiscais, frente de caixa, endereço de
acesso) ficam para depois deste piloto — não implemente agora.

## 5. Modelo de dados (por implantação)

```json
{
  "company": {"legal_name": "", "trade_name": "", "cnpj": "", "postal_code": ""},
  "cliente_padrao": {"nome": "", "cpf": "", "cep": ""},
  "instituicao_financeira": {"bank_name": "", "cnpj_banco": ""},
  "produto_ncm": {"ncm": ""},
  "contador": {"cnpj_contabilidade": ""},
  "fiscal": {"tax_regime": "", "csosn": "", "icms_rate": ""}
}
```

Campos obrigatórios por módulo (validar antes de liberar a etapa
correspondente):
- `company`: legal_name, trade_name, cnpj, postal_code
- `cliente_padrao`: nome, cpf, cep
- `instituicao_financeira`: bank_name
- `produto_ncm`: ncm
- `contador`: cnpj_contabilidade

`cnpj_banco` é opcional (pode vir de consulta automática dentro do Hiper).

## 6. Persistência (SQLite — schema mínimo)

```sql
CREATE TABLE deployments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id TEXT NOT NULL,
  hiper_account TEXT,
  environment TEXT NOT NULL DEFAULT 'homologacao',
  status TEXT NOT NULL DEFAULT 'rascunho',
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT
);

CREATE TABLE deployment_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deployment_id INTEGER NOT NULL REFERENCES deployments(id),
  step_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pendente',
  attempts INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  finished_at TEXT,
  evidence_reference TEXT,
  error_code TEXT,
  error_message_sanitized TEXT,
  UNIQUE(deployment_id, step_key)
);
```

Estados de implantação: `rascunho` → `validado` → `aguardando_confirmacao_conta`
→ `executando` → `aguardando_intervencao` / `falhou` / `homologacao_concluida`
→ `aguardando_aprovacao` → `producao_confirmada`.

Estados de etapa: `pendente`, `executando`, `concluida`,
`ignorada_justificadamente`, `falhou`, `aguardando_operador`.

## 7. Regra inegociável sobre seletores do Hiper

**Não invente seletores, URLs de telas ou comportamento do Hiper.** Cada
módulo de automação deve ter dois modos:

- `dry_run=True` (padrão): não abre navegador, apenas simula o resultado
  para permitir testar todo o resto do sistema.
- `dry_run=False`: se os seletores reais ainda não foram capturados via
  Playwright Codegen, a função deve levantar um erro explícito
  (`SelectorsNotCapturedError` ou similar) — nunca simular sucesso com
  seletor inventado. Deixe o código real comentado como esqueleto, seguindo
  sempre o ciclo: **verificar se já existe → decidir criar/editar/pular →
  preencher → salvar → reler e confirmar**.

## 8. Estrutura de projeto sugerida

```text
app/
  models.py
  services/
    contract_adapter.py     # hoje: fixture local; depois: HTTP real
    validation.py
    orchestrator.py
  automation/
    browser_session.py      # perfil persistente OU connect_over_cdp
    modules/
      clientes.py            # cliente_padrao + instituicao_financeira
      produtos.py             # produto_ncm
      contadores.py            # contador
      loja.py                   # loja_config + config_vendas
  persistence/
    db.py
    repositories.py
  security/
    redaction.py             # nunca persistir/logar segredos
  templates/                 # UI simples (Flask + Jinja2)
  static/
fixtures/
  contracts/1042.json
tests/
requirements.txt
README.md
```

## 9. Pendências que o Codex NÃO deve resolver sozinho

Sinalize estes pontos no README gerado em vez de decidir por conta própria:

1. Método real de acesso ao sistema de contratos (API, banco ou arquivo) —
   ainda não definido.
2. Origem do CNPJ da contabilidade (`contador.cnpj_contabilidade`): vem do
   contrato ou é sempre digitado pelo operador?
3. URL/domínio real do Hiper e permissões da conta de implantação.
4. Confirmação de que pessoa física (cliente) e pessoa jurídica (banco)
   realmente se cadastram em Cadastros → Clientes (ver Seção 4).
5. Como é criada a série fiscal (bloqueia o módulo de Caixas, fora desta
   fase, mas documentar a lacuna).

## 10. Critérios de aceite da Fase 1

- Rodar `pytest` sem erros, cobrindo validação, adaptador de contrato e
  repositórios.
- Em modo dry-run, é possível: importar o contrato de fixture → editar/
  completar campos na UI → validar → "executar" as 6 etapas → ver relatório
  final com evidência simulada em cada etapa.
- Em modo real, qualquer módulo sem seletores capturados recusa rodar com
  mensagem clara, em vez de fingir sucesso.
- Nenhum segredo aparece em `data_json`, logs ou capturas de tela.
- Retomar uma implantação não repete etapas já `concluida`.
- README explica como rodar em dry-run, como plugar o modo real depois da
  gravação Codegen, e lista as pendências da Seção 9.

## 11. Primeira tarefa

Implemente a Fase 1 completa conforme este brief: modelos, persistência,
adaptador de contrato (fixture), validação, orquestrador, os quatro
módulos de automação em modo dry-run com o modo real bloqueado, UI simples
em Flask para as telas de lista/revisão/execução/resultado, testes com
pytest e README. Não implemente fila, worker, login automatizado nem
automação da troca para produção. Pergunte antes de tomar qualquer decisão
listada na Seção 9.
