import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.operators.browser_operator import BrowserSession, run_task


@pytest.fixture(autouse=True)
def stable_unit_test_memory(monkeypatch, request):
    # Mock-only loops must not depend on other applications' RAM usage. The
    # optional real-browser test retains the actual production memory guard.
    if request.node.name != "test_fecap_browser_integration":
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(available=16 * 1024**3),
        )


class Session:
    def __init__(self):
        self.actions = []
        self.page = SimpleNamespace(url="https://example.org")

    def observe(self):
        return {
            "url": self.page.url,
            "title": "Catálogo",
            "text": "Seção final aberta"
            if len(self.actions) >= 2
            else "Página inicial",
            "elements": [{"ref": "e1", "name": "Próxima seção"}],
        }

    def act(self, action):
        self.actions.append(action)


def engine(*actions):
    result = MagicMock()
    result.generate.side_effect = [
        {"content": json.dumps(action)} for action in actions
    ]
    return result


def test_observe_act_verify_loop_preserves_the_entire_goal():
    session = Session()
    llm = engine(
        {"action": "navigate", "url": "https://example.org"},
        {"action": "click", "ref": "e1"},
        {"action": "done", "message": "Seção aberta", "evidence": "Seção final aberta"},
        {"complete": True, "evidence": "Seção final aberta"},
    )
    task = "Procure qualquer assunto e depois abra a seção solicitada"
    result = run_task(session, task, [], llm, "general", threading.Event())
    assert result["status"] == "completed"
    assert len(session.actions) == 2
    for call in llm.generate.call_args_list:
        payload = json.loads(call.args[0][-1].content)
        assert payload["task"] == task
        assert "observation" in payload


def test_done_without_action_or_actual_evidence_is_rejected():
    session = Session()
    llm = engine(
        *[
            {
                "action": "done",
                "message": "Vídeo aberto",
                "evidence": "Vídeo inventado",
            }
        ]
        * 3
    )
    result = run_task(session, "Abra um vídeo", [], llm, "general", threading.Event())
    assert result["status"] == "incomplete"
    assert not session.actions


def test_action_limit_returns_incomplete_instead_of_success():
    llm = engine(*[{"action": "wait"}] * 2)
    result = run_task(
        Session(), "Tarefa longa", [], llm, "general", threading.Event(), max_steps=2
    )
    assert result["status"] == "incomplete"


def test_emergency_stop_prevents_more_actions():
    stopped = threading.Event()
    stopped.set()
    llm = engine()
    result = run_task(Session(), "Qualquer tarefa", [], llm, "general", stopped)
    assert result["status"] == "stopped"
    llm.generate.assert_not_called()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)"])
def test_browser_rejects_privileged_navigation(url):
    session = BrowserSession()
    session.page = MagicMock()
    with pytest.raises(ValueError, match="HTTP"):
        session.act({"action": "navigate", "url": url})
    session.page.goto.assert_not_called()


def test_model_cannot_supply_selectors_or_arbitrary_javascript():
    session = BrowserSession()
    session.page = MagicMock()
    session.refs = {"e1"}
    with pytest.raises(ValueError, match="Referência"):
        session.act({"action": "click", "ref": "body; run()"})
    session.page.locator.assert_not_called()
    with pytest.raises(ValueError, match="desconhecida"):
        session.act({"action": "evaluate", "code": "anything"})


def test_agent_dispatches_full_task_not_just_the_search_query():
    from openjarvis.agents._stubs import AgentContext
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.core.types import ToolResult
    from openjarvis.operators.browser_operator import BrowserTaskTool

    tool = MagicMock()
    tool.spec = BrowserTaskTool().spec
    agent = OrchestratorAgent(MagicMock(), "general", tools=[tool])
    agent._executor.execute = MagicMock(
        return_value=ToolResult(
            "browser_task",
            '{"message":"Tarefa concluída"}',
            success=True,
        )
    )
    context = AgentContext()
    context.metadata["navigation_action"] = {
        "action": "browser_search",
        "app": "Firefox",
        "text": "carros elétricos",
    }
    task = "Pesquise carros elétricos e depois abra a aba Imagens"
    agent.run(task, context=context)
    call = agent._executor.execute.call_args.args[0]
    assert call.name == "browser_task"
    assert json.loads(call.arguments)["task"] == task


def test_opening_is_not_completion_and_verifier_keeps_loop_running():
    session = Session()
    llm = engine(
        {"action": "done", "evidence": "Página inicial"},
        {"action": "navigate", "url": "https://example.org"},
        {"action": "done", "evidence": "Página inicial"},
        {"complete": False, "reason": "Falta abrir o resultado"},
        {"action": "click", "ref": "e1"},
        {"action": "done", "evidence": "Seção final aberta"},
        {"complete": True, "evidence": "Seção final aberta"},
    )
    result = run_task(
        session,
        "Pesquise FECAP e abra o site oficial",
        [],
        llm,
        "general",
        threading.Event(),
    )
    assert result["status"] == "completed"
    assert [item["action"] for item in session.actions] == ["navigate", "click"]


def test_visual_frames_are_sent_once_and_not_retained():
    session = Session()
    session.capture_frame = MagicMock(return_value="jpeg-base64")
    received_images = []
    decisions = iter(
        [
            {"action": "click", "x": 15, "y": 20},
            {
                "action": "type",
                "text": "Fundação Escola de Comércio Álvares Penteado FECAP",
            },
            {"action": "press", "key": "Enter"},
            {"action": "wait", "seconds": 2},
            {"action": "click", "ref": "e1"},
            {"action": "done", "evidence": "Seção final aberta"},
            {"complete": True, "evidence": "Seção final aberta"},
        ]
    )

    def reply(messages, **kwargs):
        received_images.append(list(messages[-1].images))
        assert kwargs["num_ctx"] == 4096
        return {"content": json.dumps(next(decisions))}

    llm = MagicMock()
    llm.generate.side_effect = reply
    result = run_task(
        session,
        "Pesquise FECAP e abra o site oficial",
        [],
        llm,
        "vision",
        threading.Event(),
        vision=True,
    )
    assert result["status"] == "completed"
    assert len(session.actions) == 5
    assert all(images == ["jpeg-base64"] for images in received_images)
    assert "jpeg-base64" not in json.dumps(result)
    for call in llm.generate.call_args_list:
        assert all(message.images is None for message in call.args[0])


def test_low_memory_stops_before_capturing_or_calling_model(monkeypatch):
    monkeypatch.setattr("psutil.virtual_memory", lambda: SimpleNamespace(available=100))
    session = Session()
    session.observe = MagicMock()
    llm = engine()
    result = run_task(session, "Pesquise algo", [], llm, "general", threading.Event())
    assert result["status"] == "blocked"
    session.observe.assert_not_called()
    llm.generate.assert_not_called()


def test_screenshot_is_resized_and_buffers_are_closed():
    import base64
    import io

    from PIL import Image

    with Image.new("RGB", (1920, 1080)) as original, io.BytesIO() as buffer:
        original.save(buffer, format="JPEG")
        session = BrowserSession()
        session.page = MagicMock()
        session.page.screenshot.return_value = buffer.getvalue()
        encoded = session.capture_frame()
    with io.BytesIO(base64.b64decode(encoded)) as buffer, Image.open(buffer) as image:
        assert image.width <= 960 and image.height <= 640
    assert len(encoded) < 700000
    session.page.screenshot.assert_called_once_with(
        type="jpeg", quality=60, full_page=False, timeout=5000
    )


def test_visual_coordinates_map_to_viewport_and_become_stale():
    session = BrowserSession()
    session.page = MagicMock()
    session.page.viewport_size = {"width": 1152, "height": 768}
    session.context = SimpleNamespace(pages=[session.page])
    session.page.is_closed.return_value = False
    session.frame_size = (960, 640)
    session.act({"action": "click", "x": 480, "y": 320})
    session.page.mouse.click.assert_called_once_with(576, 384)
    with pytest.raises(ValueError, match="captura atual"):
        session.act({"action": "click", "x": 480, "y": 320})


def test_google_challenge_blocks_without_false_success():
    session = Session()
    session.page.url = "https://www.google.com/sorry/index?secret=not-retained"
    llm = engine()
    result = run_task(
        session, "Pesquise e abra o site", [], llm, "general", threading.Event()
    )
    assert result["status"] == "blocked"
    assert "secret" not in result["url"]
    llm.generate.assert_not_called()


def test_fecap_browser_integration(tmp_path):
    """Real Firefox actions; synthetic provider/pages, never claimed as live vision."""
    import os
    from urllib.parse import parse_qs, urlsplit

    if os.environ.get("RUN_BROWSER_INTEGRATION") != "1":
        pytest.skip("Set RUN_BROWSER_INTEGRATION=1 to launch Firefox")
    session = BrowserSession(headless=True, profile=tmp_path / "profile")
    phrase = "Fundação Escola de Comércio Álvares Penteado FECAP"
    submitted = []

    def serve(route):
        parsed = urlsplit(route.request.url)
        if parsed.path == "/search":
            submitted.append(parse_qs(parsed.query)["q"][0])
            html = '<title>Resultados</title><a href="/official">Site oficial FECAP</a>'
        elif parsed.path == "/official":
            html = "<title>FECAP oficial</title><h1>" + phrase + "</h1>"
        else:
            html = (
                '<title>Busca</title><form action="/search">'
                '<input name="q" style="position:absolute;left:40px;top:40px;'
                'width:400px;height:40px">'
                "<button>Pesquisar</button></form>"
            )
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

    decisions = iter(
        [
            {"action": "click", "x": 80, "y": 50},
            {"action": "type", "text": phrase},
            {"action": "press", "key": "Enter"},
            {"action": "wait", "seconds": 2},
            {"action": "click", "ref": "e1"},
            {"action": "done", "message": "Site oficial aberto", "evidence": phrase},
            {"complete": True, "evidence": phrase},
        ]
    )
    llm = MagicMock()

    def reply(messages, **kwargs):
        assert messages[-1].images  # Actual screenshot sent to provider adapter.
        return {"content": json.dumps(next(decisions))}

    llm.generate.side_effect = reply
    try:
        session.start()
        session.context.route("https://fixture.test/**", serve)
        session.page.goto("https://fixture.test/")
        result = run_task(
            session,
            "Pesquise " + phrase + " e abra o site oficial",
            [],
            llm,
            "vision-test",
            threading.Event(),
            vision=True,
        )
        assert result["status"] == "completed", result
        assert submitted == [phrase]
        assert session.page.url == "https://fixture.test/official"
        assert session.page.title() == "FECAP oficial"
    finally:
        session.close()
