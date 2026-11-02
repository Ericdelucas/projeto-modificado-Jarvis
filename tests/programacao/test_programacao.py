"""Programming routing and real FAISS/PDF round trips, without network or LLM."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.programacao.config import ProgramacaoConfig
from openjarvis.programacao.rag_books import BooksRag, OllamaEmbeddings, chunks
from openjarvis.programacao.routing import (
    _availability,
    _retriever,
    prepare_route,
    programming_intent,
)


@pytest.fixture(autouse=True)
def clear_caches():
    _availability.cache_clear()
    _retriever.cache_clear()


@pytest.mark.parametrize(
    "text",
    [
        "Escreva uma função Python",
        "Refatorar código FastAPI",
        "Debug SQL",
        "Projete a arquitetura de software",
        "Erro no backend",
        "Crie uma API",
        "```python\nprint(1)```",
    ],
)
def test_programming_intent(text):
    assert programming_intent(text)


@pytest.mark.parametrize(
    "text",
    [
        "Bom dia",
        "O que tenho na agenda?",
        "abra o Visual Studio Code",
        "Abra o Python",
        "por favor, abra o Firefox",
    ],
)
def test_system_intent(text):
    assert not programming_intent(text)


@pytest.mark.parametrize(
    "text",
    [
        "Quero que você pesquise no Firefox sobre funções Python",
        "pesquise tutoriais de FastAPI",
        "faça a pesquisa ai",
    ],
)
def test_browser_commands_do_not_switch_to_code_model(tmp_path, text):
    cfg = configuration(tmp_path)
    engine = MagicMock(engine_id="ollama")
    with patch.object(BooksRag, "context") as retrieval:
        route = prepare_route(text, cfg.programacao.code_model, cfg, engine)
    assert route.model == cfg.programacao.general_model
    assert not route.programming
    retrieval.assert_not_called()
    engine.list_models.assert_not_called()


def configuration(tmp_path):
    return SimpleNamespace(
        programacao=ProgramacaoConfig(
            enabled=True,
            books_dir=str(tmp_path / "books"),
            vector_db_dir=str(tmp_path / "db"),
        ),
        engine=SimpleNamespace(ollama=SimpleNamespace(host="http://localhost:11434")),
    )


def test_route_switches_per_request_without_changing_engine(tmp_path):
    cfg = configuration(tmp_path)
    engine = MagicMock(engine_id="ollama")
    engine.list_models.return_value = [cfg.programacao.code_model]
    code = prepare_route("Crie uma função Python", "original", cfg, engine)
    assert code.model == cfg.programacao.code_model
    assert code.context == ""  # No index -> no embedding call/dependency error.
    general = prepare_route("abra o Firefox", code.model, cfg, engine)
    assert general.model == "qwen3:1.7b"
    assert not general.programming
    prepare_route("Refatore o código", "original", cfg, engine)
    engine.list_models.assert_called_once()


def test_missing_specialist_and_broken_rag_fall_back(tmp_path):
    cfg = configuration(tmp_path)
    engine = MagicMock(engine_id="ollama")
    engine.list_models.return_value = []
    with patch.object(BooksRag, "context", side_effect=RuntimeError("offline")):
        route = prepare_route("Função Python", "missing-model", cfg, engine)
    assert route.model == "qwen3:1.7b"
    assert route.context == ""


def test_disabled_route_preserves_explicit_model(tmp_path):
    cfg = configuration(tmp_path)
    cfg.programacao.enabled = False
    engine = MagicMock(engine_id="ollama")
    assert prepare_route("Python", "explicit", cfg, engine).model == "explicit"
    engine.list_models.assert_not_called()


def test_instrumented_ollama_is_routed(tmp_path):
    cfg = configuration(tmp_path)
    inner = MagicMock(engine_id="ollama")
    inner.list_models.return_value = [cfg.programacao.code_model]
    engine = MagicMock(engine_id="instrumented", _inner=inner)
    engine.list_models.return_value = [cfg.programacao.code_model]
    assert (
        prepare_route("Python", "old", cfg, engine).model == cfg.programacao.code_model
    )


def test_multi_engine_keeps_programming_on_ollama(tmp_path):
    cfg = configuration(tmp_path)
    inner = MagicMock(engine_id="ollama")
    inner.list_models.return_value = [cfg.programacao.code_model]
    engine = SimpleNamespace(engine_id="multi", _engines=[("ollama", inner)])
    assert (
        prepare_route("Python", "old", cfg, engine).model == cfg.programacao.code_model
    )


def make_pdf(path, text):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    stream = StreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    page[NameObject("/Rotate")] = NumberObject(0)
    with path.open("wb") as output:
        writer.write(output)


def fake_embeddings(texts):
    return [[1.0, 0.0] if "python" in text.lower() else [0.0, 1.0] for text in texts]


def test_real_pdf_faiss_round_trip_removal_and_empty_index(tmp_path):
    cfg = configuration(tmp_path).programacao
    books = tmp_path / "books"
    books.mkdir()
    make_pdf(books / "Python.pdf", "Python function clean code principles")
    make_pdf(books / "SQL.pdf", "SQL indexing transactions database")
    rag = BooksRag(cfg, "unused", embed=fake_embeddings)
    assert rag.index()["chunks"] == 2
    # A new instance proves index and metadata persist on disk.
    loaded = BooksRag(cfg, "unused", embed=fake_embeddings)
    hits = loaded.search("Python function")
    assert len(hits) == 1
    assert hits[0]["source"] == "Python.pdf"
    assert hits[0]["page"] == 1
    context = loaded.context("Python")
    assert "Python.pdf" in context and "página 1" in context
    assert "SQL.pdf" not in context
    assert len(context) <= cfg.max_context_chars
    (books / "Python.pdf").unlink()
    rag.index()
    assert loaded.search("Python") == []
    (books / "SQL.pdf").unlink()
    assert rag.index()["chunks"] == 0
    assert loaded.search("SQL") == []


def test_failed_reindex_preserves_previous_snapshot(tmp_path):
    cfg = configuration(tmp_path).programacao
    books = tmp_path / "books"
    books.mkdir()
    make_pdf(books / "Book.pdf", "Python functions")
    rag = BooksRag(cfg, "unused", embed=fake_embeddings)
    rag.index()
    with patch.object(rag, "embed", side_effect=RuntimeError("offline")):
        with pytest.raises(RuntimeError, match="offline"):
            rag.index()
    assert rag.search("Python")[0]["source"] == "Book.pdf"


def test_corrupt_or_mismatched_index_is_rejected(tmp_path):
    cfg = configuration(tmp_path).programacao
    books = tmp_path / "books"
    books.mkdir()
    make_pdf(books / "Book.pdf", "Python functions")
    rag = BooksRag(cfg, "unused", embed=fake_embeddings)
    result = rag.index()
    cfg.embedding_model = "another-model"
    with pytest.raises(ValueError, match="embedding mudou"):
        rag.search("Python")
    cfg.embedding_model = "nomic-embed-text"
    folder = tmp_path / "db" / result["generation"]
    (folder / "index.faiss").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Checksum"):
        rag.search("Python")


def test_chunking_bounds_and_context_budget(tmp_path):
    text = "def f():\n    return 1\n\n" * 300
    parts = chunks(text, 1600, 200)
    assert all(len(part) <= 1600 for part in parts)
    assert any("    return 1" in part for part in parts)
    cfg = configuration(tmp_path).programacao
    cfg.max_context_chars = 256
    rag = BooksRag(cfg, "unused")
    with patch.object(
        rag,
        "search",
        return_value=[
            {
                "source": "Book.pdf",
                "page": 2,
                "text": text,
            }
        ],
    ):
        assert len(rag.context("Python")) <= 256


def test_relative_book_paths_do_not_change_with_working_directory(
    tmp_path, monkeypatch
):
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    cfg = ProgramacaoConfig()
    rag = BooksRag(cfg, "unused", embed=fake_embeddings)
    root = Path(__file__).resolve().parents[2]
    assert rag.books == root / "books-programação"
    assert rag.db == root / ".runtime/vector_db"


def test_index_reports_every_pdf_including_nested_uppercase_extension(tmp_path):
    cfg = configuration(tmp_path).programacao
    books = tmp_path / "books"
    (books / "nested").mkdir(parents=True)
    make_pdf(books / "One.pdf", "Python functions")
    make_pdf(books / "nested" / "Two.PDF", "SQL indexes")
    events = []
    result = BooksRag(cfg, "unused", embed=fake_embeddings).index(
        progress=events.append
    )
    assert result["books"] == result["pages"] == result["chunks"] == 2
    assert {event["source"] for event in events if event["stage"] == "pdf"} == {
        "One.pdf",
        "nested/Two.PDF",
    }
    assert events[-1] == {"stage": "embeddings", "done": 2, "total": 2}


def test_ollama_embedding_api_uses_batches_without_silent_truncation():
    response = MagicMock()
    response.json.return_value = {"embeddings": [[1.0], [2.0]]}
    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = response
        assert OllamaEmbeddings("http://localhost:11434", "embed")(["a", "b"])
    args = client.return_value.__enter__.return_value.post.call_args
    assert args.kwargs["json"] == {
        "model": "embed",
        "input": ["a", "b"],
        "truncate": False,
    }
