# Escopo de leitura dos assistentes

## Trabalhe por funcionalidade

- Comece pelo caminho informado pelo usuário. Não carregue a raiz inteira, não liste recursivamente todo o repositório e não leia arquivos em massa para se ambientar.
- Backend de ferramentas: comece em `src/openjarvis/tools/`; consulte somente os testes correspondentes em `tests/tools/`.
- Frontend: comece no componente em `frontend/src/components/`, hook em `frontend/src/hooks/` ou módulo em `frontend/src/lib/` relacionado ao pedido. Use `frontend/src/` como limite inicial quando o componente ainda for desconhecido.
- API: comece em `src/openjarvis/server/`. Voz: comece em `src/openjarvis/speech/` e consulte os componentes de captura ou reprodução somente se o problema atravessar essa fronteira.
- Configuração do agente: comece no arquivo de `configs/` mencionado e no módulo responsável em `src/openjarvis/agents/` ou `src/openjarvis/cli/`.
- Amplie o escopo somente quando um import, uma chamada, um erro ou um teste apontar uma dependência fora dele. Leia apenas os arquivos necessários dessa dependência.
- Use buscas delimitadas, por exemplo `rg -n 'open_app' src/openjarvis/tools tests/tools` ou `rg -n 'useSpeech' frontend/src`. Prefira trechos relevantes a arquivos completos e limite saídas extensas.
- Rode os testes relacionados à mudança. Amplie a verificação apenas quando houver dependência ou risco concreto que justifique isso.

## Exclusões de contexto

Não indexe, percorra, pesquise recursivamente nem carregue como contexto:

- `.runtime/`, `books-programação/`, `.venv/`, `venv/` e qualquer `node_modules/`;
- caches `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`, `.mypy_cache/`, `.cache/`, `.vite/` e `.vitest/`;
- `.git/`, logs, bancos de dados, modelos, gravações, arquivos binários e credenciais;
- saídas geradas: `src/openjarvis/server/static/`, `frontend/dist/`, `frontend/src-tauri/target/`, `target/`, `dist/`, `build/` e cobertura de testes;
- arquivos `*.pyc`, `*.pyo`, `*.tsbuildinfo`, `*.log` e logs rotacionados.

Esses caminhos não são código-fonte para revisão. Não leia conteúdo de credenciais, tokens ou `.env` para descobrir a configuração.

Usar executáveis como `.venv/bin/python` ou ferramentas instaladas em `frontend/node_modules/` é permitido: executar uma ferramenta não significa carregar suas dependências no contexto. Builds podem gerar arquivos nas pastas excluídas; edite o código-fonte correspondente.

Se o usuário pedir explicitamente diagnóstico de logs, modelos ou ambiente local, acesse somente o arquivo necessário e o menor trecho útil, sem varrer as pastas excluídas. Mantenha segredos fora da saída.

## Limite das exclusões

`.cursorignore` fornece os padrões de exclusão para o Cursor. Estas instruções orientam os demais agentes; não constituem bloqueio de acesso pelo sistema operacional. Não invente arquivos de ignore não suportados nem prometa que buscas de terminal seguem automaticamente `.cursorignore`.
