import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.config import JarvisConfig
from openjarvis.core.types import ToolResult
from openjarvis.operators.gui_operator import GuiControlTool
from openjarvis.server.routes import router
from openjarvis.tools._stubs import BaseTool


@pytest.mark.parametrize("stream", [False, True])
def test_semantic_plan_reaches_executor_and_overrides_code_routing(stream):
    calls = []

    class BrowserStub(BaseTool):
        tool_id = "gui_control"

        @property
        def spec(self):
            return GuiControlTool().spec

        def execute(self, **params):
            calls.append(params)
            return ToolResult(
                self.tool_id, '{"message":"Pesquisa solicitada"}', success=True
            )

    cfg = JarvisConfig()
    cfg.programacao.enabled = True
    cfg.agent.context_from_memory = False
    engine = MagicMock(engine_id="ollama")
    engine.generate.return_value = {
        "content": json.dumps(
            {
                "action": "search",
                "app": "Firefox",
                "query": "Python e receitas",
            }
        )
    }
    agent = OrchestratorAgent(engine, "qwen3:1.7b", tools=[BrowserStub()])
    app = FastAPI()
    app.include_router(router)
    app.state.engine, app.state.agent, app.state.config = engine, agent, cfg
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen2.5-coder:3b",
                "stream": stream,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Traz uns resultados da web de Python e receitas no Firefox"
                        ),
                    }
                ],
            },
        )
    assert response.status_code == 200
    assert calls == [
        {"action": "browser_search", "app": "Firefox", "text": "Python e receitas"}
    ]
    assert "Pesquisa solicitada" in response.text
    assert "qwen3:1.7b" in response.text
    engine.generate.assert_called_once()
    assert engine.generate.call_args.kwargs["model"] == "qwen3:1.7b"
