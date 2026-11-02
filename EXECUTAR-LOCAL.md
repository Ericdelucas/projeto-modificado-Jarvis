# Desenvolvimento local sem chaves externas

Execute na raiz deste repositório. A instalação encontrada já contém `.venv`,
`frontend/node_modules`, `.bootstrap/bin/uv`, `.runtime/bin/ollama` e o modelo
`qwen3:1.7b` em `.runtime/models`. Não é necessário reinstalar para iniciar.

## Terminal 1: Ollama

```bash
cd /home/eric/Documentos/GitHub/projeto-modificado-Jarvis
export OLLAMA_MODELS="$PWD/.runtime/models"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_NO_CLOUD=1
.runtime/bin/ollama serve
```

Se a porta já estiver ocupada, confira `curl http://127.0.0.1:11434/api/tags`
antes de tentar iniciar outra instância. O modelo já está baixado.

## Terminal 2: backend

```bash
cd /home/eric/Documentos/GitHub/projeto-modificado-Jarvis
export OPENJARVIS_HOME=/tmp/openjarvis-local-eric
export OPENJARVIS_CONFIG="$PWD/configs/local-dev.toml"
.venv/bin/jarvis serve --engine ollama --model qwen3:1.7b --agent orchestrator --host 127.0.0.1 --port 8000
```

O diretório em `/tmp` isola bancos e credenciais preexistentes e pode ser apagado
pelo sistema. Para manter conversas após reiniciar a máquina, use
`export OPENJARVIS_HOME="$HOME/.openjarvis-local"` antes de iniciar o backend.
Esse diretório deve ficar fora do repositório, por exigência do projeto.

## Terminal 3: frontend

```bash
cd /home/eric/Documentos/GitHub/projeto-modificado-Jarvis/frontend
OPENJARVIS_VITE_PROXY_TARGET=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Abra http://127.0.0.1:5173 e selecione `qwen3:1.7b` se solicitado.
Para encerrar, pressione Ctrl+C nos três terminais.

A interface foi adaptada para português do Brasil. A configuração local também
orienta o Qwen a responder em pt-BR por padrão. Após atualizar os arquivos,
recarregue o navegador com Ctrl+Shift+R e reinicie o backend para aplicar
mudanças na instrução do modelo.

A transcrição usa Faster-Whisper em CPU com `int8` e o modelo já existente em
`.runtime/whisper`, conforme `[speech]` em `configs/local-dev.toml`. Isso evita
a dependência das bibliotecas de GPU que estava impedindo a transcrição.
Inicie o backend pela raiz do repositório para resolver o caminho relativo do
modelo. O Qwen continua usando Ollama; essa opção de CPU vale apenas para voz.

O navegador envia `pt` explicitamente e o servidor aplica `[speech].language`
quando o formulário não informa idioma. `pt-BR` é normalizado para `pt` para
o Whisper. O microfone agora encerra a gravação automaticamente após cerca de
650 ms de silêncio depois de detectar fala; o segundo clique continua permitindo
parar manualmente. O texto é inserido no campo de mensagem, sem envio automático.
O reconhecimento ainda ocorre após finalizar a gravação, não palavra por palavra.

O filtro Silero do Whisper usa 500 ms de silêncio e 200 ms de margem para
preservar as bordas das palavras. A decodificação usa `beam_size = 3`, em vez
do padrão 5 da biblioteca, e não reutiliza texto anterior como contexto, para
reduzir repetições. São parâmetros ajustáveis no TOML. A qualidade com o seu
microfone e o ruído do ambiente ainda precisa ser conferida na prática.

Nesta máquina foi encontrado apenas `qwen3:1.7b` no Ollama. Não há modelo 7B
baixado. Trocar o LLM de conversa não altera a transcrição, que é feita pelo
Whisper. Para conferir modelos locais: `.runtime/bin/ollama list`. Se outro
modelo já estiver disponível futuramente, selecione-o no seletor da interface
ou altere `intelligence.default_model` e `--model` ao iniciar o backend.

O widget de comparação de custos está oculto no painel lateral e na página
de métricas por `VITE_SHOW_COST_COMPARISON=false` em `frontend/.env.local`.
Essa flag só controla a exibição de estimativas; não habilita nem desabilita
provedores de IA. Para reexibir, use `true` e reinicie o frontend (ou refaça
o build, quando usar a interface estática). O exemplo está em
`frontend/.env.example`.

As mensagens enviadas a esse Qwen local não consomem tokens pagos de APIs
externas. Os números de custos e economia do painel são comparações estimadas
com provedores na nuvem, não cobranças. Uma conversa no Codex/ChatGPT é um
serviço separado deste OpenJarvis local e segue as condições da conta usada.

Validação realizada: frontend HTTP 200, `/health` direto e pelo proxy com
`{"status":"ok"}`, modelo listado e resposta de chat em português recebida.
A primeira chamada excedeu 120 segundos durante a preparação inicial da GPU;
a chamada seguinte retornou normalmente. Aguarde a primeira carga do modelo.

## Instalação de dependências, se precisar reconstruir o ambiente

Python suportado: >=3.10 e <3.14. Frontend: Node >=22.22 e npm >=11.19.0 e <12,
conforme `frontend/package.json` (mais específico que a documentação antiga).

```bash
# Na raiz: instalação pelo lockfile, em ambiente novo.
UV_CACHE_DIR="$PWD/.runtime/uv-cache" .bootstrap/bin/uv sync --locked --extra server
npm --prefix frontend ci --cache "$PWD/.runtime/npm-cache"
```

`uv sync` sincroniza os extras selecionados e pode remover pacotes adicionais
do ambiente existente, inclusive os de voz. Para apenas instalar/atualizar o
backend preservando outros pacotes, use em vez disso:

```bash
UV_CACHE_DIR="$PWD/.runtime/uv-cache" .bootstrap/bin/uv pip install --python .venv/bin/python -e '.[server]'
```

As instalações podem acessar registros públicos, mas não exigem tokens pagos.
Rust/Cargo e o grupo `desktop-native` pertencem à extensão nativa e ao desktop;
a inicialização web mínima funciona sem essa compilação, embora registre aviso
do limitador de requisições nativo ausente.

## Configuração

- `configs/local-dev.toml`: configuração mínima criada para esta execução;
  usa o motor Ollama integrado, agente `orchestrator`, ferramentas locais e analytics desligado.
- Sem override, a configuração é `~/.openjarvis/config.toml`.
- Não é necessário `.env` para este fluxo. `deploy/docker/.env.example` é
  específico do Docker; sua `OPENJARVIS_API_KEY` é autenticação da API local,
  não uma chave de provedor de IA.
- `configs/openjarvis/config.toml` é um exemplo de avaliação GLM/vLLM em A100,
  inadequado como configuração mínima para esta execução.
- Não usei o script preexistente `iniciar-jarvis.sh`: ele inclui configuração
  adicional de voz e depende da configuração global.

## Verificação

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:5173/health
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:1.7b","messages":[{"role":"user","content":"Responda apenas: funcionando /no_think"}],"max_tokens":64,"stream":false}'
```

## Voz neural em português (interface web)

O Modo Voz envia a resposta concluída para `POST /api/tts` com JSON
`{"text":"Olá! Como posso ajudar você hoje?"}` e reproduz o MP3 retornado
com um player HTML5. A voz é fixa: `pt-BR-AntonioNeural`.
A rota remove Markdown, blocos de código e raciocínio antes da leitura.
`GET /api/tts/health` informa se a biblioteca está instalada; não testa
conectividade com o serviço remoto.

A dependência `edge-tts` está registrada em `pyproject.toml` e `uv.lock`.
Em um ambiente existente, instale sem remover outros pacotes de voz:

```bash
UV_CACHE_DIR="$PWD/.runtime/uv-cache" .bootstrap/bin/uv pip install --python .venv/bin/python edge-tts
```

Edge TTS requer internet e envia o texto para o serviço de síntese da Microsoft.
Não usa a voz do navegador nem os modelos XTTS para esse fluxo da interface.
Falhas de rede aparecem junto ao botão de leitura da mensagem, que permite
repetir a tentativa. Trocar de modo interrompe a reprodução ou solicitação pendente.

### Reprodução progressiva e ritmo de conversa

O chat envia frases completas durante a geração do modelo, com fila e
pré-carregamento da frase seguinte. `POST /api/tts/stream` transmite os bytes
MP3 do Edge conforme chegam. Em navegadores com MediaSource para MP3, o player
começa após os primeiros bytes decodificáveis. Webviews sem esse suporte usam
clipes por frase; não aguardam a resposta inteira do modelo. A primeira palavra
isolada não é sintetizada, pois isso perde contexto e entonação.

A voz Antonio usa `rate=-5%` e `pitch=-2Hz`, sem alterar artificialmente a
velocidade do player. A limpeza remove emojis, símbolos decorativos, URLs,
Markdown e blocos de código; pausas são inseridas em orações longas.
Ao parar a fala, mudar de modo/conversa ou começar outra mensagem, a fila e
as solicitações pendentes são canceladas. O serviço continua exigindo internet.

## Palavra de ativação offline: computador

Dependências: `vosk`, `sounddevice` (registradas no projeto). O detector usa
Vosk porque os modelos padrão do openWakeWord não incluem “computador”.
O reconhecimento da palavra é totalmente local; o áudio contínuo não é salvo
nem enviado a serviços externos. A transcrição do pedido continua no Whisper.

Baixe o modelo uma vez, pela raiz do projeto:

```bash
.venv/bin/python scripts/install/setup-wakeword.py
```

Na barra superior, clique em **Escuta Contínua (Palavra de Ativação)** e permita
o uso do microfone no navegador na primeira vez. Isso também seleciona o
Modo Voz. Depois diga **computador**, aguarde o beep e fale o pedido: o campo
mostra **Ouvindo…**, e o gravador encerra pela pausa de silêncio já existente.
O texto transcrito aparece no campo de mensagem, mantendo o envio por Enter.

O worker captura o microfone da máquina onde o backend está executando,
não o de um navegador remoto. Precisa da aba do chat conectada por SSE.
O botão permite desativar e libera o microfone. Modo Escrita/Desligado e
fechamento da aba também encerram a escuta. Apenas uma aba recebe a ativação;
a escuta fica temporariamente pausada durante gravação, transcrição, geração
e reprodução de voz para evitar reativação pela própria resposta.

PortAudio é usado quando disponível (`libportaudio2` no Linux). Nesta máquina,
a biblioteca não está instalada e o worker usa `parec` via PulseAudio/PipeWire,
que já está disponível. Em outro ambiente, instale PortAudio ou `pulseaudio-utils`.

Variáveis opcionais:

- `OPENJARVIS_WAKE_MODEL`: caminho do modelo Vosk português.
- `OPENJARVIS_WAKE_DEVICE`: dispositivo sounddevice (índice ou nome).
- `OPENJARVIS_WAKE_PULSE_SOURCE`: nome da fonte PulseAudio; padrão: microfone padrão.

API: `/api/wakeword/status`, `/control`, `/heartbeat` e `/events` (SSE), com a
mesma autenticação das demais rotas `/api`. Não há captura ao iniciar o servidor:
a escuta é ligada explicitamente pelo controle na interface.

### Diagnóstico da palavra de ativação

O indicador do microfone pisca em verde somente quando chegam blocos de áudio
recentes e eles estão sendo processados pelo Vosk. O medidor mostra nível em dBFS;
o texto abaixo informa a última fala reconhecida e a confiança da palavra-chave,
ou “parcial estável” quando não há escore numérico. Pausas mostram o motivo
(`tts`, `gravando`, `transcrevendo`, `gerando`, `modelo` ou `cooldown`).
“Sem conexão” indica falha no SSE; “Sem áudio do microfone” indica ausência de
blocos recentes, mesmo que o serviço esteja habilitado.

Logs em `.runtime/logs/jarvis.log`:

```bash
rg '\[wakeword\]' .runtime/logs/jarvis.log
```

O backend registra RMS, volume, dBFS, total de bytes e blocos processados a cada
segundo; palavras parciais/finais são registradas quando mudam. Registra também
a fonte do microfone, conexão/desconexão SSE e cada ativação. Esse diagnóstico
inclui o texto reconhecido nos logs, mas não salva o áudio. Para desativar esses
logs, inicie com `OPENJARVIS_WAKE_DEBUG=0`.

O alias aceita “computador” e “computer”. Instale ambos os modelos offline com:

```bash
.venv/bin/python scripts/install/setup-wakeword.py --english
```

`OPENJARVIS_WAKE_EN_MODEL` permite mudar o caminho do modelo inglês.
`OPENJARVIS_WAKE_THRESHOLD` ajusta a confiança exigida para palavras finais
(padrão `0.65`). Parciais sem escore precisam permanecer estáveis em três blocos
consecutivos. `/api/wakeword/status` inclui `diagnostics`, `audio_source`,
`aliases`, `languages` e `threshold`. O console do navegador mostra conexão SSE,
ativação recebida e eventual bloqueio do gravador pelo estado da interface.

## Google Calendar: agenda de hoje no chat

A ferramenta `google_calendar_today` consulta o calendário principal ao vivo,
com acesso somente de leitura. Ela está habilitada em `configs/local-dev.toml`
e no conjunto padrão do servidor. O agente local configurado é `orchestrator`,
que permite ao Qwen chamar ferramentas. O agente `simple` não chama ferramentas.
O script `iniciar-jarvis.sh` usa a configuração local por padrão e preserva um
`OPENJARVIS_CONFIG` definido externamente.

### Autorizar sua conta uma vez

1. No Google Cloud, habilite a Google Calendar API e configure a tela de
   consentimento OAuth. Para uma conta pessoal em app de teste, inclua seu
   próprio e-mail nos usuários de teste.
2. Crie um cliente OAuth do tipo **Aplicativo para computador / Desktop app**
   e baixe o JSON. Salve-o fora do repositório, por exemplo em
   `~/.openjarvis/credentials/google-calendar-client.json`. Não envie esse
   arquivo nem o token para o chat ou para o Git.
3. Pela raiz do projeto, execute:

```bash
export OPENJARVIS_CONFIG="$PWD/configs/local-dev.toml"
.venv/bin/jarvis calendar connect --client-secrets "$HOME/.openjarvis/credentials/google-calendar-client.json"
```

O navegador abrirá para o consentimento de leitura. O retorno OAuth usa somente
`127.0.0.1`, em porta temporária, com estado OAuth e PKCE gerenciados pela
biblioteca oficial. O token fica em
`$OPENJARVIS_HOME/credentials/google-calendar-token.json` ou, sem override,
`~/.openjarvis/credentials/google-calendar-token.json` (arquivo `0600`, diretório
`0700`). O token é renovado automaticamente; a ferramenta nunca inicia login
interativo em uma pergunta do modelo. O token não fica no repositório.

Alternativas para apontar o cliente OAuth: `OPENJARVIS_GOOGLE_CLIENT_SECRETS`
ou `[google_calendar].client_secrets`. A ferramenta de consulta ao vivo usa
este login somente de leitura, separado da sincronização de fontes de dados.

### Consultar e conferir

```bash
.venv/bin/jarvis calendar status
.venv/bin/jarvis calendar today
```

No chat: **“O que eu tenho para hoje?”**, **“Qual minha agenda?”** ou
**“Quais são meus compromissos?”**. O Qwen recebe os dados da ferramenta e
responde em português. Se não houver eventos, a resposta orientada é:
**“Você não tem nenhum compromisso agendado para hoje.”**

O fuso é `America/Araguaina` na configuração local. Sem fuso explícito, o cliente
usa `TZ` ou o fuso IANA detectado no sistema. A busca vai de meia-noite local
até a meia-noite seguinte (limite exclusivo), cobrindo também `23:59:59.999` e
dias com mudança de horário. Inclui todas as páginas, eventos recorrentes e de
dia inteiro; horários com offset são convertidos para o fuso da consulta.
Erros de autenticação/API retornam status de erro, nunca uma agenda vazia.

Referências oficiais:
- https://developers.google.com/workspace/calendar/api/quickstart/python
- https://developers.google.com/workspace/calendar/api/v3/reference/events/list

## Abrir aplicativos locais no Ubuntu

`open_app` descobre aplicativos dinamicamente, sem catálogo fixo. Procura arquivos
`.desktop` em `$XDG_DATA_HOME/applications` (normalmente
`~/.local/share/applications`), nos diretórios de `$XDG_DATA_DIRS` (incluindo
`/usr/share/applications`) e nas exportações de Snap e Flatpak.

No chat, use o nome amigável: “Abra o Android Studio”, “Abra o Firefox”,
“Abra o Google Chrome” ou “Abra o Visual Studio Code”. A busca considera nomes
traduzidos, nomes genéricos, palavras-chave e identificadores `.desktop`.
“Abra o navegador” consulta o navegador padrão configurado no desktop.
Entradas do usuário têm prioridade; `Hidden=true` mascara a entrada do sistema.
Se houver ambiguidade, a ferramenta retorna os nomes e arquivos encontrados.
Novas instalações são descobertas na próxima chamada, sem editar o código.

O GIO (`gio launch`) abre a entrada real instalada, preservando comandos Exec,
argumentos, variáveis de ambiente, ativação D-Bus e opções de terminal. Sem GIO,
a ferramenta extrai o Exec e expande os campos Desktop Entry (%c, %k, %i, %%);
os campos de arquivos/URLs são omitidos porque essa chamada só abre o app.
Se não houver entrada correspondente, procura o executável no PATH, sem lista
de nomes permitidos. Também aceita caminhos executáveis, incluindo AppImages.

A abertura permanece em segundo plano, com `start_new_session=True` e sem shell.
O campo `app` recebe um nome/caminho, não uma linha de comandos shell.
A aplicação abre na máquina e sessão gráfica do backend. Políticas RBAC
explícitas continuam exigindo `code:execute`. Reinicie o backend para carregar
esta versão da ferramenta.

Referência do formato Exec:
https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html
