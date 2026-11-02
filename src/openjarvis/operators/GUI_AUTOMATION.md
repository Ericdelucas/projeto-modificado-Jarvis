# Automação de desktop

O módulo `gui_operator.py` registra a ferramenta `gui_control`, habilitada em
`configs/local-dev.toml` e na seleção padrão de ferramentas do servidor.
PyAutoGUI e pyperclip fazem parte do extra `desktop` e estão instalados neste ambiente.

## Usar no chat ou por voz

```text
abra o Firefox e pesquise documentação do FastAPI
abra o Chrome e pesquise orientação a objetos em Python
Quero que você pesquise no Firefox sobre Felipe Neto
faça a pesquisa aí
pare a automação
reativar automação
```

São apenas exemplos, não um catálogo de frases aceitas. No chat web, os pedidos
de pesquisa são interpretados semanticamente pelo modelo geral. Somente as
travas de emergência usam o caminho imediato sem chamar o modelo. O comando de
voz deve ser transcrito e enviado ao chat, usando o fluxo existente.

O modelo interpreta o pedido antes do roteamento de programação, retorna JSON
e não executa nada
nessa etapa; o agente executa a ferramenta após validar a decisão. A consulta deve
ser um trecho literal do pedido atual ou do histórico recente do usuário. Se o
modelo reescrever um termo e o trecho não for localizado, a pesquisa usa o pedido
original completo, sem inventar o termo ou bloquear o assunto. Uma
decisão inválida retorna erro, em vez de uma confirmação de pesquisa fictícia.
Essa interpretação usa até quatro mensagens anteriores, com tamanho limitado,
e acrescenta uma chamada curta ao modelo para interpretar o pedido.

O tema da consulta é livre. A ferramenta aceita `query` (ou o campo `text`
existente) e preserva o termo literal, incluindo acentos e pontuação. Pedidos de
continuação usam a última pesquisa nas mensagens do usuário da conversa atual;
sem consulta anterior, retornam erro em vez de confirmar uma pesquisa inexistente.
Pesquisas são ações gerais, mesmo quando o termo contém Python ou outra linguagem.

## Compatibilidade real com Ubuntu

- **X11 / Ubuntu on Xorg:** enumeração e foco de janelas, movimento, clique,
  digitação, atalhos da pesquisa e screenshots pelo PyAutoGUI.
- **Wayland (sessão atual):** pesquisas são abertas por uma URL HTTP(S) no
  aplicativo escolhido, via sua entrada `.desktop`. Isso funciona sem simular
  cliques ou teclas. A ferramenta retorna `method: browser_url`.
- Mouse, teclado e screenshots por PyAutoGUI são recusados em Wayland: ele não
  controla de forma confiável janelas nativas dessa sessão. A implementação não
  desativa as proteções do compositor nem simula sucesso.

Para usar todas as ações, encerre a sessão do Ubuntu e selecione **Ubuntu on Xorg**
na engrenagem da tela de login. Não é necessário para pesquisar no Firefox.

Textos ASCII são digitados com intervalo de 20 ms entre caracteres. Texto Unicode
usa a área de transferência e Ctrl+V; no X11, instale `xclip` ou `xsel` caso não
haja um provedor de clipboard. Essa ação substitui o conteúdo do clipboard.
Screenshots dependem de Pillow e de um capturador compatível, como
`gnome-screenshot`, disponível neste Ubuntu.

## Ações da ferramenta

| action | Parâmetros | Efeito |
| --- | --- | --- |
| `windows` | — | Lista ID, título e classe das janelas X11. |
| `focus` | `app` | Ativa e confirma a janela escolhida. |
| `move` | `x`, `y` | Move em 0,3 s dentro dos limites da tela principal. |
| `click` | `x`, `y` | Move e realiza um clique esquerdo. |
| `type` | `app`, `text` | Confirma o foco antes de digitar até 2.000 caracteres. |
| `screenshot` | — | Salva um PNG em `.runtime/gui/screenshots/` com permissão 0600. |
| `browser_search` | `app`, `text` | Abre o navegador e envia uma pesquisa. |
| `stop` | — | Interrompe e bloqueia novas ações até rearmar. |
| `resume` | — | Rearma depois que a ação anterior terminou e o cursor saiu do canto. |

Exemplo de parâmetros:

```json
{"action": "browser_search", "app": "Firefox", "text": "Python funções"}
```

## Trava de emergência

Erros comuns, como aplicativo ausente, coordenada inválida ou controle não
suportado no Wayland, não acionam uma parada permanente das próximas tarefas.
Quando houver parada de segurança, a interface mostra **Automação pausada** com
o botão **Reativar**; o mesmo pode ser feito dizendo “reativar automação”.
Pedidos naturais para iniciar aplicativos também são encaminhados ao launcher
dinâmico, sem depender exclusivamente da frase “abra o aplicativo”.

No X11, `pyautogui.FAILSAFE` fica sempre ativado. Mova o mouse para **qualquer
um dos quatro cantos da tela principal** para interromper a automação. Um monitor
adicional observa o cursor a cada 30 ms; as operações também conferem o estado
entre os caracteres e passos. A interrupção bloqueia novas ações até `resume`.
Chamadas nativas em andamento precisam retornar para que o Python propague a falha.

O operador permite uma ação por vez, aplica um limite de 30 segundos e interrompe
a digitação se a janela perder o foco. Nunca desative o failsafe. A pesquisa X11
confirma o foco antes de usar Ctrl+L, digitar a consulta literal e pressionar Enter.

O resultado informa a ação executada; enviar uma pesquisa não comprova que uma
página carregou ou que uma operação dentro dela foi concluída. Screenshots são
arquivos locais: este módulo não acrescenta interpretação visual ao modelo textual.

Documentação de referência:
[PyAutoGUI e failsafe](https://pyautogui.readthedocs.io/en/latest/index.html).

## Executor de navegação em várias etapas

`browser_task` está habilitado em `configs/local-dev.toml`. O agente encaminha
TODO o pedido ao executor, em vez de encerrar depois de abrir uma URL.
`computer_use/agent.py` observa a página após cada ação, recupera erros transitórios
e exige uma segunda verificação do objetivo antes de retornar `completed`.
CAPTCHA do Google retorna `blocked`, sem afirmar que abriu o resultado.
O trabalho roda no worker dedicado, fora do event loop da API.

O Firefox controlado usa um perfil próprio; não assume controle de uma janela
Firefox pessoal já aberta. Playwright permite controlar seu conteúdo em Wayland,
mas isso não implementa captura ou controle global do desktop via PipeWire.

Configuração em `[computer_use]`:

- `vision_model = ""`: usa o modelo geral leve com observações DOM. Não é visão.
- `vision_model = "qwen3.5:9b"`: envia a captura atual ao Ollama para decisões
  visuais. Exige RAM disponível acima de `vision_min_available_mb` (8192 MiB por
  padrão); não habilite enquanto a máquina estiver sob pressão de memória.
- `num_ctx = 4096`: limita o contexto em todas as decisões e verificações.
- `max_steps = 24`, `timeout = 180.0`: limites de execução.
- `min_available_mb = 1536`: interrompe antes da próxima captura/inferência quando
  falta memória. Essa reserva não garante ausência de OOM em outros processos.

As capturas visuais contêm apenas o viewport, são reduzidas a 960x640 e JPEG de
até 512 KiB. Os buffers são fechados, as mensagens perdem o campo de imagem após
cada chamada e nenhuma captura entra no histórico de ações. Cliques por coordenada
são convertidos da imagem reduzida para o viewport e invalidados após cada ação.

Validação automatizada com Firefox real e páginas/provedor simulados:

```bash
RUN_BROWSER_INTEGRATION=1 .venv/bin/python -m pytest \
  tests/operators/test_browser_operator.py::test_fecap_browser_integration -q
```

Esse teste verifica clique, texto com acentos, Enter, espera de dois segundos,
abertura de resultado e URL final. Não comprova percepção por um LLM real nem
remove bloqueios impostos pelo Google.
