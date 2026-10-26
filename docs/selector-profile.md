# Capturar o perfil da interface Hiper

Nenhum perfil de produção foi incluído. Não copie os seletores de
`tests/fixtures/hiper-profile.json`: eles pertencem somente à página de teste.

1. Execute `python scripts/inspect_hiper.py --domain SEU_TENANT --snapshot`.
2. Conclua login/MFA no Chromium visível e abra a tela de filiais.
3. Pressione Enter no terminal. O utilitário imprime roles, labels, test IDs
   e links sem valores de formulário, cookies ou storage. Sem marcador de
   autenticação mapeado, não salva screenshot nem estado autenticado.
4. Crie um JSON local com seletores observados. `captured_from` registra
   ambiente/tela/data; nunca inclua login, senha ou token.
5. Configure `HIPER_SELECTOR_PROFILE` para o caminho desse JSON.
6. Rode de novo com `--profile CAMINHO --debug` para inspecionar a sessão.
7. Valide descoberta e dry-run antes de permitir escrita real.

## Esquema (valores precisam ser capturados)

| Chave | Tipo / função |
|---|---|
| `captured_from` | String com origem/data do levantamento |
| `authenticated` | Seletor exclusivo de usuário autenticado no tenant |
| `login_required` | Seletor opcional da tela de login/expiração |
| `auth_probe_path` | Rota de leitura capturada para testar sessão no servidor |
| `stores.path` ou `stores.link` | Rota relativa ou link da UI para filiais |
| `stores.ready` | Marcador de lista carregada, inclusive lista vazia |
| `stores.rows` | Seletor das linhas/cartões de filiais |
| `stores.cnpj`, `stores.name` | Seletores relativos à linha |
| `stores.link_to_settings` | Link relativo à linha, com `href` da filial |
| `stores.id_attribute` | Atributo da linha que contém ID, se existir |
| `stores.id_from_url_regex` | Alternativa: regex capturada da rota, grupo 1 = ID |
| `general_data.path_template` | Opcional, rota observada com `{store_id}` |
| `general_data.link` | Opcional, link da aba de dados gerais |
| `general_data.cnpj` | Campo/elemento com CNPJ da filial; somente leitura |
| `general_data.store_name` | Nome da filial na tela, especialmente para atalho URL/ID |
| `general_data.fields` | Dicionário de campos não fiscais e seus seletores |
| `general_data.save` | Botão de salvar observado |
| `general_data.saved` | Confirmação da operação de salvar observada |
| `sensitive` | Lista de seletores de blocos a mascarar em evidências |

Formatos: `{"role":"button","name":"nome observado"}`,
`{"label":"rótulo observado"}`, `{"test_id":"valor observado"}`,
`{"text":"texto observado"}` ou `{"css":"seletor estável observado"}`.
Lista desses objetos define fallback controlado. Mais de um elemento é erro,
inclusive no primeiro candidato; não se escolhe o primeiro para escrita.

Campos permitidos: `trade_name`, `apelido`, `email`, `postal_code`, `logradouro`,
`bairro`, `municipio`, `uf`. Valores vazios/ausentes não apagam dados existentes.
CNPJ, razão social legal, IE, NCM e CSC não são editados pela primeira etapa.

A lista precisa conter o universo aplicável; paginação/virtualização ainda não
está implementada. Capture e implemente navegação de todas as páginas se necessário.
Perfis não são gerados automaticamente: exigem revisão no ambiente autorizado.
Mudanças na interface interrompem a execução, com erro explícito.
