from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.config import JarvisConfig
from openjarvis.programacao.routing import _availability
from openjarvis.server.routes import router


def test_new_code_model_is_used_even_if_navigation_interpreter_rejects_code():
    _availability.cache_clear()
    cfg = JarvisConfig()
    cfg.agent.context_from_memory = False
    cfg.programacao.enabled = True
    cfg.programacao.code_model = "qwen3.5:9b"
    engine = MagicMock(engine_id="ollama")
    engine.list_models.return_value = ["qwen3.5:9b"]
    engine.generate.side_effect = [
        {"content": '{"action":"code"}'},
        {"content": "def soma(a, b): return a + b", "usage": {}},
    ]
    agent = MagicMock()
    agent._tools = [SimpleNamespace(spec=SimpleNamespace(name="gui_control"))]
    app = FastAPI()
    app.include_router(router)
    app.state.engine, app.state.agent, app.state.config = engine, agent, cfg
    with patch("openjarvis.programacao.rag_books.BooksRag.context", return_value=""):
        with TestClient(app) as client:
            result = client.post(
                "/v1/chat/completions",
                json={
                    "model": "qwen3:1.7b",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Escreva uma função Python soma(a, b)",
                        }
                    ],
                },
            )
    assert result.status_code == 200
    assert result.json()["model"] == "qwen3.5:9b"
    assert engine.generate.call_args.kwargs["model"] == "qwen3.5:9b"
    agent.run.assert_not_called()
