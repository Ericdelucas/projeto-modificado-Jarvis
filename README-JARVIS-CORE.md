# Jarvis-Core Daemon

Executor isolado em `src/openjarvis/daemon/controller.py`. Usa `asyncio` e uma API
remota para planejar; não chama Ollama, não carrega modelos locais e não usa o
worker de inferência do `browser_operator`. O gateway antigo permanece separado.

Não existe consumo zero de RAM: Python, capturas e Firefox continuam usando
memória. A economia vem de não executar inferência local, não acumular frames e
fechar o Firefox controlado ao terminar cada tarefa. Aplicativos nativos abertos
pelo usuário continuam consumindo seus próprios recursos.

## Preparar uma vez

As dependências foram adicionadas ao extra `daemon` e ao lockfile. No checkout:

```bash
UV_CACHE_DIR="$PWD/.runtime/uv-cache" .bootstrap/bin/uv pip install \
  --python .venv/bin/python -e '.[daemon]'
PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/playwright" \
  .venv/bin/python -m playwright install firefox
cp -n jarvis-core.env.example .env.jarvis-core
chmod 600 .env.jarvis-core
```

Edite `.env.jarvis-core` e preencha `JARVIS_CORE_API_KEY` e `JARVIS_CORE_MODEL`.
O arquivo já está ignorado pelo Git. Use o identificador de um modelo visual
oferecido pelo seu provedor. Não há download automático nem modelo presumido.

A API deve implementar Chat Completions com `image_url`, JSON mode e `max_tokens`.
`JARVIS_CORE_BASE_URL` termina em `/v1`, sem `/chat/completions`. O cliente exige
HTTPS remoto, recusa IPs locais/localhost e não segue redirecionamentos. Não há
fallback para Ollama. Falhas de autenticação ou execução interrompem a tarefa.
O provedor remoto pode cobrar pelas requisições.

Formato de imagem usado pela integração:
[documentação oficial de imagens](https://developers.openai.com/api/docs/guides/images-vision?api-mode=chat).

## Executar pelo terminal

A partir da raiz, com o arquivo de ambiente preenchido:

```bash
.venv/bin/python -m openjarvis.daemon --mode web \
  'Pesquise Fundação Escola de Comércio Álvares Penteado FECAP no Google e abra o site oficial.'
```

Para classificar automaticamente entre web e desktop:

```bash
.venv/bin/python -m openjarvis.daemon \
  'Abra o Firefox, pesquise documentação de Python e abra o resultado oficial.'
```

Para desktop **em sessão X11**:

```bash
.venv/bin/python -m openjarvis.daemon --mode desktop \
  'Abra o editor de texto e digite: teste do Jarvis-Core.'
```

Outro arquivo pode ser indicado com `--env-file caminho/.env`.
A saída é JSON com `status`, `message` e ações realizadas. Código de saída zero
somente quando o objetivo foi verificado; bloqueio, falha ou interrupção retorna 1.
A execução por CLI atende uma tarefa e termina. Para manter o controlador vivo e
submeter várias tarefas, use a API Python abaixo; não há servidor HTTP público.
O chat existente não é redirecionado automaticamente para este novo subsistema.

## API Python interna

```python
import asyncio
from openjarvis.daemon.config import DaemonConfig
from openjarvis.daemon.controller import JarvisCoreDaemon

async def main():
    config = DaemonConfig.from_env('.env.jarvis-core')
    async with JarvisCoreDaemon(config) as core:
        result = await core.run(
            'Pesquise documentação de asyncio e abra o site oficial.',
            mode='web',
        )
        print(result)
        # Reutilize core.run(...) para outros objetivos, um por vez.
        # Outra coroutine pode chamar core.stop() durante a execução.

asyncio.run(main())
```

Para integrar um botão de emergência, mantenha a instância e chame `core.stop()`;
o método é síncrono e apenas sinaliza o evento de parada, sem esperar pelo modelo.

## Execução e segurança

- Web: reutiliza `BrowserSession` do operador existente, somente DOM/referências,
  sem capturas ou cliques por coordenadas. Todos os acessos ao Playwright ocorrem
  na mesma thread dedicada, sem bloquear o event loop. Perfil separado em
  `.runtime/jarvis-core/firefox/`.
- Desktop: PyAutoGUI em X11, captura JPEG até 960x640 e 512 KiB, coordenadas
  convertidas para a tela, foco obrigatório antes de interagir e failsafe nativo.
  **Wayland não está implementado para desktop global**: retorna erro explícito,
  exigindo adaptador autorizado RemoteDesktop/ScreenCast. Web funciona em Wayland.
- O desktop completo é enviado ao provedor remoto no modo visual. Não há gravação
  de capturas nem histórico de imagens. Use uma sessão sem informações sensíveis.
- Limite máximo de 10 ações; abertura, foco e espera também contam. Uma observação
  final permite verificar o objetivo após a décima ação, sem executar a décima
  primeira. Reduza o limite com `JARVIS_CORE_MAX_STEPS`.
- Monitor independente verifica RAM a cada 50 ms. Abaixo de
  `JARVIS_CORE_MIN_AVAILABLE_MB` (1536 por padrão), sinaliza parada e cancela a
  espera pela API. Movimentos de mouse são divididos em passos curtos e verificam
  o sinal; nenhuma nova ação é enviada depois da parada.
- `Ctrl+C`, SIGTERM e `core.stop()` interrompem. Uma chamada nativa já enviada
  precisa retornar; não é possível desfazer uma tecla ou clique já executado.
- Em erro de execução/foco/API, encerra sem tentar ações seguintes. O prazo global
  padrão é 120s, com até 25s por chamada remota. Encerramento de chamada nativa
  pendente pode acrescentar o tempo necessário para sua liberação.
- Um lock de processo impede duas instâncias deste daemon de controlarem a sessão
  ao mesmo tempo. Não execute simultaneamente o operador antigo e este daemon.
- CAPTCHA/login retornam bloqueio: DOM não elimina proteções anti-bot.
- Uma segunda avaliação remota verifica a conclusão. Isso reduz confirmações
  falsas, mas não constitui prova infalível de compreensão visual.

## Validar sem consumir API ou carregar modelos

```bash
.venv/bin/python -m pytest tests/daemon -q
RUN_BROWSER_INTEGRATION=1 .venv/bin/python -m pytest \
  tests/daemon/test_core.py::test_real_firefox_with_remote_transport -q
```

Os testes simulam a API remota. O teste opcional usa Firefox real com páginas
controladas; não comprova qualidade de um modelo/provedor ainda não configurado.
