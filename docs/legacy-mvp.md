# Integrador Hiper Gestão — Fase 1

> Documento histórico do MVP anterior. As instruções atuais estão no README
> da raiz e em architecture.md. O prompt de evolução substitui o escopo antigo.

MVP de uma ponte entre o sistema de contratos e a configuração assistida do
Hiper Gestão. O operador importa e revisa os dados, confirma explicitamente a
conta/loja já autenticada e executa sete etapas rastreáveis.

O modo padrão é **dry-run**: o fluxo inteiro funciona sem abrir navegador. O
modo real está intencionalmente bloqueado até que os seletores sejam capturados
no ambiente correto por meio do Playwright Codegen.

## Escopo implementado

- importação do contrato `1042` por adaptador de fixture local;
- revisão e complemento dos dados com validação;
- confirmação explícita da conta/loja e identificação do operador;
- SQLite com implantações e estado individual das sete etapas;
- orquestrador sequencial e retomável, sem repetir etapas concluídas;
- seis módulos de automação cobrindo as sete etapas em dry-run;
- configuração de 15 entradas de bandeiras de cartão na etapa de vendas em dry-run;
- recusa explícita de cada módulo em modo real sem seletores capturados;
- relatório final com tentativas, evidências simuladas e erros sanitizados;
- remoção de segredos antes da persistência e sanitização de mensagens;
- testes do adaptador, validação, repositórios, orquestração e fluxo web.

Não fazem parte desta fase: fila ou worker, cadastro de conta, automação de
login/MFA/CAPTCHA, promoção automática de homologação para produção, séries
fiscais, frente de caixa e os módulos adiados no brief.

## Executar em dry-run

Requer Python 3.10 ou superior. No PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

Acesse `http://127.0.0.1:5000`, mantenha o contrato `1042` no campo de
importação e siga o fluxo. O banco é criado em `instance/integrador.sqlite3`.

O fluxo operacional é:

1. importar o contrato;
2. revisar, editar e validar os dados;
3. fazer manualmente o login no Hiper;
4. conferir a conta/loja exibida;
5. informar conta e operador e marcar a confirmação explícita;
6. informar a senha do usuário na tela de execução;
7. iniciar as sete etapas e consultar o relatório.

Para executar os testes:

```powershell
python -m pytest
```

## API de contratos e segredos

O dry-run local usa a fixture por padrão. Para importar da API real, configure
as variáveis de ambiente antes de iniciar o processo (veja `.env.example`):

```powershell
$env:CONTRACT_SOURCE = "api"
$env:CONTRATOS_API_URL = "https://seu-servidor-de-contratos"
$env:CONTRATOS_API_TOKEN = "token-obtido-no-sistema-de-contratos"
$env:FLASK_SECRET_KEY = "chave-aleatoria-da-instalacao"
python run.py
```

O endpoint esperado é `GET /api/contratos/{id}`, com autenticação Bearer e
JSON no formato das seções da fixture. A API informa na tela token inválido
(401), contrato ausente (404), timeout/conexão indisponível e erro inesperado.
O token é criado no sistema de contratos; este projeto apenas o consome. O
arquivo `.env.example` serve de referência e não é carregado automaticamente.

Na importação, o adaptador devolve `data` e `secrets` separados. Somente `data`
vai para o SQLite. Senha e referência do certificado são descartadas após
a importação. O CSC fica apenas na memória do servidor e pode ser substituído
no campo de token das Configurações de NFC-e; reiniciar o servidor apaga esse
valor. `redaction.py` continua como segunda proteção antes de qualquer
gravação. Quando a etapa de cupom fiscal ou certificado digital for adicionada,
ela deverá buscar o contrato novamente, manter o segredo apenas no escopo da
etapa e descartá-lo ao terminar. Já existe um utilitário para baixar o arquivo
do certificado na hora do uso, com timeout separado de 60 segundos e remoção
do arquivo temporário ao sair do escopo. As sete etapas atuais não usam esses
segredos.

Na revisão, o cliente padrão tem número; a instituição financeira tem nome
fantasia, CNPJ obrigatório, CEP e número. O produto padrão usa sempre nome
`Produto padrão`, NCM `2022.10.00`, código interno `1` e unidade
`UN - Unidade`. A seção Usuários coleta nome, usuário e perfil (administrador,
gerente ou caixa). O botão `+` adiciona outro bloco para cadastrar vários usuários
na mesma implantação. O botão `−` remove o bloco correspondente, mantendo pelo
menos um usuário. Cada usuário tem sua própria senha na tela de execução.
As senhas são digitadas apenas ao iniciar a execução e passadas
somente à etapa de usuário em memória; não entram no SQLite, nos logs ou no
relatório. A etapa de usuário funciona em dry-run. A criação real no Hiper
continua bloqueada até capturar os seletores no ambiente correto.

Na seção Empresa, o apelido é opcional e a inscrição estadual pode ser marcada
como isenta. A seção Fiscal inclui a busca automática da NF-e, Caixas,
Configurações de NFC-e, Configurações de Pix e Recebimentos. Caixas usa os
botões `+` e `−` para adicionar e remover blocos de número e série fiscal,
mantendo pelo menos um bloco. Contratos antigos com um único caixa continuam
compatíveis; após revisar, os caixas são salvos como uma lista.
Nas Configurações de NFC-e, o número de identificação é salvo como texto
(preservando zeros à esquerda), e o token CSC fica somente na memória do
servidor, sem ser devolvido ao navegador ou gravado no SQLite. O CSOSN da
tributação permanece separado.
Nas Configurações de Pix, a conta bancária começa vazia na importação e o
Cliente/fornecedor é preenchido a partir do banco informado anteriormente.
O interruptor Pedido de venda controla a impressão do nome fantasia da loja
no pedido de venda e no orçamento. A confissão de dívida
usa sempre `Tenho ciência da divida no valor de R$ [ValorDocumento]`, e o
número de vias do comprovante é sempre `1`. Certificado digital, senha do
certificado vêm do contrato; a tela mostra apenas se foram recebidos.
Esses valores são descartados após a importação e precisarão ser buscados
novamente quando as etapas fiscais reais forem implementadas. Os novos
campos são de revisão; a automação fiscal real ainda depende dos seletores.

O botão Consultar CNPJ da seção Empresa consulta a BrasilAPI após o usuário
informar 14 dígitos. A rota local `GET /api/cnpj?cnpj=...` remove a formatação e
consulta `https://brasilapi.com.br/api/cnpj/v1/{cnpj}`. Razão social, nome
fantasia, logradouro, bairro, cidade e UF são preenchidos automaticamente.
A seção Instituição financeira também tem o botão Consultar CNPJ. Ele preenche
razão social do banco, nome fantasia, CEP e número; o nome é refletido em
Cliente/fornecedor no Fiscal. A tela mostra o andamento e erros de CNPJ inválido,
não encontrado, timeout ou falha do serviço. Os dados continuam editáveis e são
salvos ao clicar em Validar e continuar.

A seção Conexão de venda contém Bandeiras de cartão. A credenciadora é
obrigatória e começa vazia; uma única credenciadora é aplicada às 15 entradas.
Cliente/fornecedor usa o banco da Instituição financeira, atualizado também
ao consultar ou editar o nome desse banco. American Express, Aura, Elo,
Hipercard, Mastercard, Sorocred e Visa têm crédito e débito; Voucher tem uma
única entrada. A lista é definida pelo integrador e não pode ser alterada
pelo formulário. A credenciadora e o banco são exibidos na confirmação, e o
relatório da etapa `config_vendas` registra cada destino simulado.

A configuração é salva no SQLite junto aos demais dados. Alterar a
credenciadora ou a identificação do banco após concluir vendas torna apenas
essa etapa pendente para a próxima execução. Dados antigos sem credenciadora
precisam ser completados na revisão antes de executar vendas. A execução
real continua bloqueada: é necessário capturar a navegação e os controles
em Configurações → Conexão de venda → Bandeiras de cartão. A implementação
real deverá identificar cada linha por bandeira e modalidade, conferir os
valores existentes, editar apenas quando necessário, salvar e reler. Uma
linha ausente ou ambígua deverá interromper a etapa com sua identificação.

Cada início de execução registra operador e horário UTC na auditoria exibida
no relatório. O operador é informado na confirmação da conta.

Execute o integrador como processo contínuo na máquina do operador ou em uma
VM/servidor da rede interna com disco persistente para o SQLite. O navegador
visível e a espera pelo login manual fazem parte do fluxo. Configure
`DATABASE_PATH` se o banco precisar ficar fora da pasta `instance/`.

## Etapas

| Ordem | Chave | Responsabilidade |
|---:|---|---|
| 1 | `cliente_padrao` | localizar ou cadastrar o cliente padrão |
| 2 | `instituicao_financeira` | localizar ou cadastrar o banco |
| 3 | `produto_ncm` | editar o NCM do produto padrão |
| 4 | `contador` | adicionar o CNPJ da contabilidade |
| 5 | `loja_config` | ajustar dados da loja |
| 6 | `config_vendas` | vincular o cliente padrão, ajustar vendas e configurar as 15 bandeiras de cartão |
| 7 | `usuarios` | criar o usuário e atribuir o perfil |

Etapas já marcadas como `concluida` são ignoradas ao retomar. Uma falha de
validação ou ausência de seletores muda a etapa para `aguardando_operador` e a
implantação para `aguardando_intervencao`.

## Conectar o modo real depois do Codegen

Nenhum seletor, URL ou comportamento do Hiper foi presumido. Atualmente,
definir `HIPER_DRY_RUN=false` faz o primeiro módulo recusar a execução com
`SelectorsNotCapturedError`, que é o comportamento de segurança esperado.

Após resolver as pendências abaixo e ter acesso ao ambiente correto:

1. use o Playwright Codegen para gravar as interações reais;
2. substitua os esqueletos em `app/automation/modules/` preservando, em cada
   módulo, o ciclo **verificar existência → criar/editar/pular → preencher →
   salvar → reler e confirmar**;
3. use uma das funções de `app/automation/browser_session.py`: perfil
   persistente visível ou conexão CDP a um Chrome já aberto;
4. garanta que o operador fez login manualmente e confirme a conta na UI;
5. acrescente testes com páginas controladas e só então execute com:

```powershell
$env:HIPER_DRY_RUN = "false"
python run.py
```

O robô não deve preencher usuário, senha, MFA ou CAPTCHA. Diretórios de perfil
e estado autenticado não devem ser versionados. Evidências também não devem
conter credenciais ou segredos.

## Pendências que exigem decisão do responsável

Estas questões permanecem deliberadamente abertas, conforme a Seção 9 do
brief. Nenhuma delas foi decidida pela implementação:

1. **API de contratos:** informar URL, token Bearer e confirmar que a resposta
   do endpoint usa o formato esperado das seções da fixture.
2. **CNPJ da contabilidade:** definir se vem do contrato ou se é sempre
   digitado pelo operador.
3. **Acesso ao Hiper:** informar URL/domínio real e permissões da conta de
   implantação.
4. **Local dos cadastros:** confirmar se pessoa física (cliente) e pessoa
   jurídica (banco) são ambas cadastradas em **Cadastros → Clientes**. Os
   nomes atuais das etapas refletem o brief, mas não há navegação real.
5. **Série fiscal:** definir como ela é criada antes de um futuro módulo de
   Caixas; essa lacuna bloqueia aquele módulo, que está fora desta fase.

## Estrutura

```text
app/
  automation/       # sessão e limites dos módulos Playwright
  persistence/      # schema e repositórios SQLite
  security/         # redação de segredos
  services/         # adaptador, validação e orquestração
  static/            # estilo da UI
  templates/         # lista, revisão, execução e relatório
fixtures/contracts/1042.json
tests/
run.py
```

Os dados da fixture são fictícios e destinados somente a homologação/testes.
