"""Desktop safety and dispatch, without touching the real mouse/keyboard."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.types import ToolResult
from openjarvis.operators.gui_operator import GuiOperator, browser_search_intent


@pytest.fixture
def operator():
    op = GuiOperator()
    pg = MagicMock()
    pg.FAILSAFE_POINTS = [(0, 0), (1919, 0), (0, 1079), (1919, 1079)]
    pg.position.return_value = (100, 100)
    pg.size.return_value = (1920, 1080)
    op._pg = pg
    with patch("openjarvis.operators.gui_operator.wayland", return_value=False):
        yield op, pg


@pytest.mark.parametrize("corner", [(0, 0), (1919, 0), (0, 1079), (1919, 1079)])
def test_corner_watchdog_latches_stop(operator, corner):
    op, pg = operator
    with pytest.raises(RuntimeError, match="pausada"):
        with op.control():
            pg.position.return_value = corner
            assert op.stopped.wait(timeout=0.3)
    assert op.stopped.is_set()
    assert pg.FAILSAFE is True
    assert pg.PAUSE == 0.15
    with pytest.raises(RuntimeError):
        op.execute("move", x=50, y=50)
    pg.moveTo.assert_not_called()
    pg.position.return_value = (100, 100)
    op.execute("resume")
    assert not op.stopped.is_set()


@pytest.mark.parametrize("x,y", [(-1, 1), (1920, 1), (1, 1080), (True, 10), (0, 0)])
def test_invalid_coordinates_never_move_mouse(operator, x, y):
    op, pg = operator
    with pytest.raises(ValueError):
        op.execute("click", x=x, y=y)
    pg.moveTo.assert_not_called()
    pg.click.assert_not_called()


def test_move_then_click_is_bounded(operator):
    op, pg = operator
    op.execute("click", x=200, y=100)
    pg.moveTo.assert_called_once_with(200, 100, duration=0.3)
    pg.click.assert_called_once_with(button="left")


def test_stop_works_without_display_or_importing_pyautogui():
    op = GuiOperator()
    with patch.object(op, "backend") as backend:
        op.execute("stop")
    assert op.stopped.is_set()
    backend.assert_not_called()


def test_type_focuses_target_and_checks_each_character(operator):
    op, pg = operator
    with patch.object(op, "focus") as focus:
        op.execute("type", app="Firefox", text="abc")
    focus.assert_called_once_with("Firefox")
    assert pg.write.call_count == 3
    pg.write.assert_any_call("a", interval=0.02, _pause=False)


def test_wayland_blocks_mouse_without_loading_pyautogui():
    op = GuiOperator()
    with patch("openjarvis.operators.gui_operator.wayland", return_value=True):
        with pytest.raises(RuntimeError, match="Xorg"):
            op.execute("move", x=100, y=100)
    assert op._pg is None
    assert not op.stopped.is_set()


def test_unsupported_wayland_action_does_not_poison_later_searches():
    op = GuiOperator()
    with (
        patch("openjarvis.operators.gui_operator.wayland", return_value=True),
        patch(
            "openjarvis.tools.open_app.OpenAppTool.execute",
            return_value=ToolResult(
                "open_app",
                '{"message":"Pesquisa solicitada"}',
                success=True,
            ),
        ),
    ):
        with pytest.raises(RuntimeError, match="Xorg"):
            op.execute("click", x=10, y=10)
        assert (
            op.execute("browser_search", app="Firefox", text="macarrão")["method"]
            == "browser_url"
        )


def test_native_failsafe_still_latches_until_explicit_resume(operator):
    op, pg = operator

    class Emergency(Exception):
        pass

    pg.FailSafeException = Emergency
    pg.failSafeCheck.side_effect = Emergency("canto de emergência")
    with pytest.raises(Emergency):
        op.execute("click", x=10, y=10)
    assert op.stopped.is_set()


def test_natural_app_request_uses_launcher_not_gui_actions():
    from openjarvis.agents._stubs import AgentContext
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.tools._stubs import ToolSpec

    tool = MagicMock()
    tool.spec = ToolSpec(name="open_app", description="Apps", parameters={})
    agent = OrchestratorAgent(MagicMock(), "general", tools=[tool])
    agent._executor.execute = MagicMock(
        return_value=ToolResult(
            "open_app",
            '{"message":"Abertura solicitada"}',
            success=True,
        )
    )
    ctx = AgentContext()
    ctx.metadata["navigation_action"] = {"action": "open_app", "app": "Android Studio"}
    agent.run("Quero usar o Android Studio, inicia pra mim?", context=ctx)
    call = agent._executor.execute.call_args.args[0]
    assert call.name == "open_app"
    assert json.loads(call.arguments) == {"app": "Android Studio"}


def test_wayland_can_rearm_url_search_without_pyautogui():
    op = GuiOperator()
    with patch("openjarvis.operators.gui_operator.wayland", return_value=True):
        op.execute("stop")
        op.execute("resume")
    assert not op.stopped.is_set()
    assert op._pg is None


def test_loss_of_focus_stops_keyboard_actions(operator):
    op, pg = operator
    op.focused_window = 123
    with patch("Xlib.display.Display") as display:
        root = display.return_value.screen.return_value.root
        root.get_full_property.return_value.value = [456]
        with pytest.raises(RuntimeError, match="perdeu o foco"):
            op.check()
    assert op.stopped.is_set()
    pg.write.assert_not_called()


def test_wayland_search_uses_encoded_url_without_keyboard():
    op = GuiOperator()
    result = ToolResult("open_app", '{"message":"solicitado"}', success=True)
    with (
        patch("openjarvis.operators.gui_operator.wayland", return_value=True),
        patch(
            "openjarvis.tools.open_app.OpenAppTool.execute", return_value=result
        ) as launch,
    ):
        assert (
            op.execute("browser_search", app="Firefox", text="ação & Python")["method"]
            == "browser_url"
        )
    launch.assert_called_once_with(
        app="Firefox",
        url="https://www.google.com/search?q=a%C3%A7%C3%A3o+%26+Python",
    )


def test_x11_search_waits_for_focus_before_address_bar(operator):
    op, pg = operator
    result = ToolResult(
        "open_app", '{"message":"solicitado","app":"Firefox"}', success=True
    )
    with (
        patch("openjarvis.tools.open_app.OpenAppTool.execute", return_value=result),
        patch.object(op, "focus") as focus,
        patch.object(op, "type_text") as type_text,
    ):
        result = op.execute("browser_search", app="Firefox", text="Python testes")
    focus.assert_called_once_with("Firefox", timeout=15)
    pg.hotkey.assert_called_once_with("ctrl", "l")
    type_text.assert_called_once_with("Python testes")
    pg.press.assert_called_once_with("enter")
    assert result["method"] == "gui"


def test_focus_failure_never_types_or_presses_enter(operator):
    op, pg = operator
    result = ToolResult("open_app", '{"message":"solicitado"}', success=True)
    with (
        patch("openjarvis.tools.open_app.OpenAppTool.execute", return_value=result),
        patch.object(op, "focus", side_effect=RuntimeError("sem foco")),
        pytest.raises(RuntimeError, match="sem foco"),
    ):
        op.execute("browser_search", app="Firefox", text="Python")
    pg.hotkey.assert_not_called()
    pg.press.assert_not_called()


def test_concurrent_actions_are_rejected(operator):
    op, _ = operator
    with op.control():
        with pytest.raises(RuntimeError, match="andamento"):
            op.execute("click", x=10, y=10)


def test_deadline_stops_work(operator):
    op, _ = operator
    op.deadline = time.monotonic() - 1
    with pytest.raises(RuntimeError, match="30 segundos"):
        op.check()


def test_chat_intents_preserve_query_and_emergency_commands():
    assert browser_search_intent("abra o Firefox e pesquise Python & FastAPI") == {
        "action": "browser_search",
        "app": "Firefox",
        "text": "Python & FastAPI",
    }
    assert browser_search_intent("pare a automação") == {"action": "stop"}
    assert browser_search_intent("reativar automação") == {"action": "resume"}
    assert browser_search_intent("abra o Firefox") is None


@pytest.mark.parametrize(
    "query",
    [
        "Felipe Neto",
        "receita de pão de queijo",
        "C++ & Qt: ação, preço?",
        '"Python" OR "redes sociais"',
        "tutoriais de maquiagem",
    ],
)
@pytest.mark.parametrize(
    "command",
    [
        "Quero que você pesquise no Firefox sobre {}",
        "pesquise no Firefox sobre {}",
        "abra o Firefox e pesquise {}",
    ],
)
def test_search_topics_are_literal_and_unrestricted(query, command):
    assert browser_search_intent(command.format(query)) == {
        "action": "browser_search",
        "app": "Firefox",
        "text": query,
    }


def test_repeat_search_uses_only_prior_user_request():
    history = [
        "abra o Firefox e pesquise Python",
        "Quero que você pesquise no Firefox sobre Felipe Neto",
    ]
    assert browser_search_intent("faça a pesquisa ai", history) == {
        "action": "browser_search",
        "app": "Firefox",
        "text": "Felipe Neto",
    }
    assert browser_search_intent("faça a pesquisa aí")["text"] == ""
    assert (
        browser_search_intent("pesquise sobre outra pessoa", history)["app"]
        == "Firefox"
    )


def test_agent_executes_contextual_search_instead_of_generating_confirmation():
    from openjarvis.agents._stubs import AgentContext
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.core.types import Message, Role
    from openjarvis.tools._stubs import ToolSpec

    context = AgentContext()
    context.conversation.add(
        Message(
            role=Role.USER,
            content="Quero que você pesquise no Firefox sobre Felipe Neto",
        )
    )
    context.conversation.add(Message(role=Role.ASSISTANT, content="Pesquisa realizada"))
    tool = MagicMock()
    tool.spec = ToolSpec(name="gui_control", description="GUI", parameters={})
    engine = MagicMock()
    agent = OrchestratorAgent(engine, "test", tools=[tool])
    agent._executor.execute = MagicMock(
        return_value=ToolResult(
            "gui_control",
            '{"message":"Pesquisa solicitada"}',
            success=True,
        )
    )
    agent.run("faça a pesquisa ai", context=context)
    call = agent._executor.execute.call_args.args[0]
    assert json.loads(call.arguments) == {
        "action": "browser_search",
        "app": "Firefox",
        "text": "Felipe Neto",
    }
    engine.generate.assert_not_called()


def test_tool_accepts_literal_query_argument():
    from openjarvis.operators.gui_operator import GuiControlTool

    with patch("openjarvis.operators.gui_operator.get_gui_operator") as operator:
        operator.return_value.execute.return_value = {"message": "solicitada"}
        result = GuiControlTool().execute(
            action="browser_search", app="Firefox", query="Felipe Neto & Python?"
        )
    assert result.success
    operator.return_value.execute.assert_called_once_with(
        action="browser_search",
        app="Firefox",
        text="Felipe Neto & Python?",
    )


def test_orchestrator_calls_gui_instead_of_treating_search_as_app_name():
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.tools._stubs import ToolSpec

    tool = MagicMock()
    tool.spec = ToolSpec(name="gui_control", description="GUI", parameters={})
    engine = MagicMock()
    agent = OrchestratorAgent(engine, "test", tools=[tool])
    agent._executor.execute = MagicMock(
        return_value=ToolResult(
            "gui_control",
            '{"message":"Pesquisa solicitada"}',
            success=True,
        )
    )
    result = agent.run("abra o Firefox e pesquise Python")
    call = agent._executor.execute.call_args.args[0]
    assert call.name == "gui_control"
    assert json.loads(call.arguments)["text"] == "Python"
    assert result.content == "Pesquisa solicitada"
    engine.generate.assert_not_called()
