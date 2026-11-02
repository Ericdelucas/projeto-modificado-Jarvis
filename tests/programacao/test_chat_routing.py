"""Exercise both API paths and the server-agent context handoff."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.config import JarvisConfig
from openjarvis.programacao.config import ProgramacaoConfig
from openjarvis.programacao.routing import _availability, _retriever
from openjarvis.server.routes import router


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("with_agent", [False, True])
def test_chat_routes_model_and_only_injects_retrieved_reference(stream, with_agent):
    from openjarvis.agents._stubs import AgentResult

    _availability.cache_clear()
    _retriever.cache_clear()
    cfg = JarvisConfig()
    cfg.agent.context_from_memory = False
    cfg.programacao = ProgramacaoConfig(enabled=True)
    engine = MagicMock(engine_id="ollama")
    engine.list_models.return_value = ["qwen3:1.7b", "qwen2.5-coder:3b"]
    engine.generate.return_value = {"content": "Código em português", "usage": {}}
    stream_calls = []

    async def generate_stream(messages, **kwargs):
        stream_calls.append((messages, kwargs))
        yield "Código em português"

    engine.stream = generate_stream
    agent = MagicMock() if with_agent else None
    if agent:
        agent._model = "original"
        agent._tools = ["tool"]
        agent.run.return_value = AgentResult(content="Código em português", turns=1)
    app = FastAPI()
    app.include_router(router)
    app.state.engine, app.state.agent, app.state.config = engine, agent, cfg
    with (
        patch(
            "openjarvis.programacao.rag_books.BooksRag.context",
            return_value=(
                "Referência única [Clean Code.pdf — página 10]: funções pequenas"
            ),
        ) as retrieval,
        TestClient(app) as client,
    ):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3:1.7b",
                "stream": stream,
                "messages": [{"role": "user", "content": "Crie uma função Python"}],
            },
        )
        assert response.status_code == 200
        if stream:
            assert '"model": "qwen2.5-coder:3b"' in response.text
        else:
            assert response.json()["model"] == "qwen2.5-coder:3b"
        if with_agent:
            agent.run.assert_not_called()
            assert agent._model == "original"
        if stream:
            messages, kwargs = stream_calls[-1]
            assert kwargs["model"] == "qwen2.5-coder:3b"
        else:
            messages = engine.generate.call_args.args[0]
            assert engine.generate.call_args.kwargs["model"] == "qwen2.5-coder:3b"
        assert any("Clean Code.pdf" in message.content for message in messages)
        retrieval.assert_called_once()
        client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen2.5-coder:3b",
                "stream": stream,
                "messages": [{"role": "user", "content": "Bom dia"}],
            },
        )
        retrieval.assert_called_once()  # General requests do not access the RAG.
        if with_agent:
            agent.run.assert_called_once()
