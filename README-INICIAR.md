# Iniciar o OpenJarvis no Ubuntu

Para adicionar livros PDF e usar o modelo especialista em código, veja o
[guia do módulo de programação](src/openjarvis/programacao/README.md).

## Copiar e colar no terminal

Para esta instalação, copie o bloco inteiro abaixo. Ele verifica o Ollama,
inicia o serviço se necessário, garante o modelo configurado e abre o backend
e o frontend no navegador.

```bash
(
  set -e
  cd /home/eric/Documentos/GitHub/projeto-modificado-Jarvis
  export OPENJARVIS_CONFIG="$PWD/configs/local-dev.toml"
  mkdir -p .runtime

  if ! ollama list >/dev/null 2>&1; then
    nohup ollama serve > .runtime/ollama.log 2>&1 &
    for tentativa in {1..30}; do
      if ollama list >/dev/null 2>&1; then break; fi
      sleep 1
    done
    ollama list >/dev/null
  fi

  ollama pull qwen3:1.7b
  uv run --extra desktop jarvis gui
)
```

Abra **http://127.0.0.1:5173** se o navegador não abrir sozinho.
O backend atende em **http://127.0.0.1:8000**.
Mantenha o terminal aberto durante o uso. O primeiro início pode demorar para
baixar dependências e o modelo; nas próximas vezes, os arquivos são reutilizados.

O comando usa `configs/local-dev.toml`, com o agente em português e as ferramentas
locais configuradas. Ele não precisa refazer a autorização do Google Calendar
quando o token salvo ainda é válido.

## Parar o projeto

Em outro terminal, copie:

```bash
cd /home/eric/Documentos/GitHub/projeto-modificado-Jarvis
uv run --extra desktop jarvis stop
```

Isso encerra o frontend e o backend gerenciados pelo Jarvis. O Ollama continua
disponível para outros aplicativos. `Ctrl+C` no terminal da interface encerra
somente o frontend; use o comando acima para encerrar também o backend.

## Verificar o backend

```bash
curl --fail http://127.0.0.1:8000/health
```

Para consultar o estado dos serviços gerenciados:

```bash
cd /home/eric/Documentos/GitHub/projeto-modificado-Jarvis
uv run --extra desktop jarvis status
```

## Requisitos e problemas comuns

- Este guia pressupõe Ubuntu com **uv**, **Ollama**, **Python 3.10 a 3.13**, **Node.js 22.22 ou superior** e **npm 11.19.x** instalados. As dependências Python são resolvidas pelo `uv`, e o comando `gui` instala as dependências do frontend quando necessário.
- Se o projeto estiver em outra pasta, ajuste o caminho do `cd`.
- Se a porta 5173 estiver ocupada por uma execução anterior, pare o projeto antes de iniciar novamente. Se houver um backend iniciado manualmente na porta 8000, encerre-o no terminal de origem antes de usar este guia.
- Se o Ollama não iniciar, consulte `.runtime/ollama.log`.
- Se a interface mostrar uma versão antiga, pressione **Ctrl+Shift+R**.
- Para usar voz e microfone, permita o acesso ao microfone no navegador. A síntese atual com `edge-tts` precisa de internet; o chat com Ollama executa localmente.
- O reconhecimento de voz usa um modelo Whisper local apontado em `configs/local-dev.toml`. Em outra máquina, esse caminho precisa corresponder a um modelo instalado.
