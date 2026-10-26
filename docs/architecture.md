# Integração Hiper: arquitetura e decisões

## Base examinada

O repositório real é Flask/Jinja, HTTPX, SQLite e Playwright, não FastAPI.
A factory `app/__init__.py` contém importação, revisão, execução e relatório.
Sete etapas e seus testes já existem; os módulos reais recusam execução sem
seletores. A versão anterior oferece somente simulação sem navegador.
Baseline em 08/10/2026: 67 testes aprovados, 3 testes de navegador opcionais.
Preservamos Flask, modelos, revisões e dados existentes. O novo prompt substitui
as restrições de escopo do brief antigo, mantendo login exclusivamente manual.

## Resolução de tenant e filial

| Estratégia | Benefício | Limitação |
|---|---|---|
| A: URL completa | Atalho determinístico | Acopla contrato às rotas; não prova identidade |
| B: domínio + descoberta | CNPJ encontra a filial | Exige mapeamento autorizado da lista |
| C: seleção do operador | Resolve ambiguidade | Seleção ainda exige validar CNPJ |
| D: híbrida | Aceita A/B/C com validação comum | Mais estados explícitos |

Adotada D. URL completa e ID são dicas, nunca autorização. A lista é descoberta
na UI mapeada; CNPJ exato tem precedência. Cache/ID/nome ajudam a encontrar uma
candidata, mas somente CNPJ coincidente na tela de dados gerais autoriza escrita.
Duas filiais com mesmo CNPJ exigem seleção explícita; nunca escolher a primeira.
Domínios são HTTPS sob `hiper.com.br`; URL, domínio e base conflitantes são
rejeitados. URLs locais só existem nos testes com configuração explícita.

## Responsabilidades

- `app/config.py`: configuração única e defaults conservadores.
- `app/api/hiper.py`: endpoints JSON, validação, autorização local e painel.
- `app/services/hiper_deployment.py`: execução retomável, pausa e modos.
- `app/automation/hiper/`: browser async, autenticação manual, seletores
  capturados, navegação, resolução, evidências e etapas.
- `app/persistence/hiper.py`: contexto da filial, cache, auditoria e locks SQLite.
- Revisão e simulação legadas permanecem compatíveis. Execução real só pelo
  novo serviço e nunca pelo antigo orquestrador.

Um loop asyncio dedicado mantém os objetos Playwright na mesma thread.
HTTP apenas agenda trabalho; consulta de status continua disponível durante
execução. Nenhuma senha de usuário, CSC ou certificado atravessa a persistência.
Autenticação abre browser visível; operador conclui login/MFA/CAPTCHA. Estado
é salvo por tenant somente após marcador autenticado confirmado. Sessão é
revalidada ao navegar e antes de salvar; expiração vira `awaiting_auth`.

## Seletores e primeira etapa

Não existe acesso autorizado ao Hiper nesta sessão. O perfil de produção começa
vazio. `scripts/inspect_hiper.py` permite levantamento local autorizado e
`docs/selector-profile.md` documenta o esquema. Seletores precisam de origem
documentada, marcador autenticado e rotas capturadas. Dados gerais implementa
INSPECT → VALIDATE → EXECUTE → VERIFY (reload e leitura dos valores).
Somente campos não fiscais do perfil são alterados. CNPJ é só leitura.
Usuários e demais módulos reais continuam explicitamente não mapeados.
Testes de browser usam HTML controlado, não afirmam compatibilidade com Hiper.

## Modos, concorrência e retomada

`simulation`: sem browser, evidencia simulação. `dry_run`: browser, leitura,
identificação e comparação, sem fill/save. `real`: exige flag do servidor,
contrato de API (fixture proibida), confirmação explícita, operador e CNPJ.
Resultado de simulação/dry-run nunca é reutilizado como sucesso real.
Retomada começa na primeira etapa não concluída e revalida a identidade da filial;
nova execução explícita reinspeciona também os concluídos. Alterações de revisão invalidam
somente etapas relevantes, e identidade alterada invalida contexto/consentimento.

Locks SQLite por tenant e tenant+filial são atômicos, com lease renovável;
serialização por tenant também protege a página compartilhada. Outras instâncias
recebem 409. Antes de escrever confirma-se a propriedade do lease. Após crash,
lease expira; retomada reinspeciona estado e não assume se save ocorreu.
Pausa é cooperativa entre etapas; operação de save já iniciada termina/verifica.

## Segurança e limites

API mutante exige token CSRF de sessão local; requisições de outros hosts são
recusadas. Processo atende localhost por padrão. Para uso em rede, publicar
atrás de autenticação/TLS e configurar host/secret; não é um sistema multiusuário.
Estado autenticado e artefatos são privados, ignorados pelo Git e separados por
tenant. No Windows aplica-se ACL ao usuário corrente. Evidência mascara campos
de formulário e só é capturada em página com marcador autenticado; HTML exportado
é uma representação permitida de roles/labels/links, sem scripts, valores ou
storage. URL exportada perde query e fragmento. Erros Playwright brutos não são
expostos, pois podem conter valores preenchidos.

SQLite é suficiente para operação local; repository isola SQL para futura
migração. Execução fiscal real/A1/A3 permanece bloqueada; dados fiscais exigem
aprovação contábil. Nenhum NCM/tributo é inventado pela nova execução real.
