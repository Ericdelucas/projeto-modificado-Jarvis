# Programação: roteamento e livros locais

Toda a política de classificação, consulta técnica e processamento dos PDFs
fica neste diretório. `server/routes.py` apenas conecta o módulo ao chat;
`core/config.py` carrega a seção `[programacao]`.

## Preparação

Na raiz do projeto, com o Ollama rodando:

```bash
uv sync --extra desktop --extra programacao
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
mkdir -p 
-programação .runtime/vector_db
```

Nesta instalação, os modelos e dependências já foram preparados. Se os comandos
não estiverem no PATH, use `.bootstrap/bin/uv` e `.runtime/bin/ollama`.
O extra `desktop` também inclui as dependências do RAG, para que `jarvis gui`
não as remova ao sincronizar o ambiente.

## Adicionar livros e indexar

Copie PDFs com texto selecionável para `books-programação/`, na raiz do projeto.
Essa é a pasta padrão do indexador e da configuração local. Em seguida:

```bash
OPENJARVIS_CONFIG="$PWD/configs/local-dev.toml" \
  .venv/bin/python -m openjarvis.programacao.rag_books index
```

O comando extrai texto por página, mantém a identificação do livro e da página,
divide em trechos de até 1.600 caracteres com sobreposição de 200, gera embeddings
em lotes via Ollama `/api/embed` e grava um índice FAISS de similaridade cosseno.
Os livros e vetores permanecem locais, nas pastas ignoradas pelo Git e assistentes.
Não há envio a serviços de embeddings na nuvem.

Execute `index` novamente ao adicionar, alterar ou remover livros. A reconstrução
é explícita: o chat nunca indexa PDFs durante uma pergunta. Cada reconstrução
publica um snapshot completo; uma falha mantém o anterior. Snapshots antigos
continuam em disco para não interromper leitores em andamento.

PDFs de imagens precisam de OCR externo; PDFs protegidos precisam ser
desbloqueados previamente. Não há OCR automático neste módulo. A saída mostra
avisos para livros sem texto extraível. Não foram incluídos livros de terceiros.

## Testar a recuperação

```bash
OPENJARVIS_CONFIG="$PWD/configs/local-dev.toml" \
  .venv/bin/python -m openjarvis.programacao.rag_books query \
  "Como organizar funções pequenas e testáveis em Python?"
```

A busca retorna somente os trechos acima do limiar, com livro, página e score.
Sem índice ou sem correspondência relevante, retorna uma lista vazia.

## Comportamento no chat

- Conversas, agenda e abertura de aplicativos usam `general_model`.
- Escrita de código, refatoração e depuração usam `code_model`, se instalado.
- A seleção do especialista usa regras locais. A camada de navegação pode
  interpretar o pedido antes; uma decisão inválida dessa camada não bloqueia
  pedidos identificados como programação.
- A seleção é por requisição, incluindo streaming. Ela não muda o modelo global
  do agente e a próxima pergunta geral volta ao modelo leve.
- Tarefas de programação seguem a inferência direta, sem o loop de ferramentas
  de sistema/agenda. Isso mantém o escopo isolado e suporta especialistas que
  não aceitam chamadas de ferramentas.
- Só tarefas de programação consultam os livros. O prompt recebe no máximo
  `top_k` trechos e `max_context_chars` caracteres de referência, incluindo fontes.
- Conteúdo dos PDFs é tratado como referência não confiável, nunca como instrução.
  O modelo é orientado a citar livro e página quando usar a referência.
- Se o especialista não estiver instalado, o sistema usa o modelo geral e emite
  um aviso no log. Falhas de embeddings/índice não derrubam o chat: ele prossegue
  sem referência e registra o motivo. Não afirma ter consultado livros inexistentes.

## Configuração

Edite `[programacao]` em `configs/local-dev.toml` e reinicie o backend:

```toml
[programacao]
enabled = true
general_model = "qwen3:1.7b"
code_model = "qwen3.5:9b"
rag_enabled = true
embedding_model = "nomic-embed-text"
books_dir = "books-programação"
vector_db_dir = ".runtime/vector_db"
chunk_chars = 1600
chunk_overlap = 200
top_k = 3
min_score = 0.35
max_context_chars = 4800
embedding_timeout = 15.0
indexing_timeout = 120.0
```

Nesta cópia do código, os caminhos relativos são resolvidos a partir da raiz
do projeto, mesmo se o processo for chamado de outra pasta. Execute os comandos
documentados na raiz para localizar o ambiente virtual e a configuração.
Trocar o modelo de embeddings exige
reindexação. O limite é de caracteres, não uma contagem exata de tokens.
Modelos do Ollama recém-instalados são detectados em até dez segundos.
O tempo máximo por lote na indexação é maior que o da consulta, para tolerar
o primeiro carregamento do modelo sem alongar as requisições do chat.
`enabled = false` preserva a seleção original de modelo do cliente.

O módulo não executa o código sugerido pelo modelo.

Referências de implementação: [Ollama embeddings](https://docs.ollama.com/api/embed),
[FAISS e similaridade cosseno](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes)
e [extração com pypdf](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md).
