"""WhatsApp Web tool over a fake Firefox WebDriver BiDi socket (no browser)."""

import json

import pytest

from openjarvis.connectors.whatsapp_web import WhatsAppUnavailable, WhatsAppWebClient
from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.whatsapp_web import WhatsAppTodayTool

PAGE = {
    "logged_in": True,
    "chats": [
        {
            "chat": "Ana",
            "last_message": "Oi!",
            "time": "09:12",
            "unread": 2,
            "last_from_me": False,
        },
        {
            "chat": "Bruno",
            "last_message": "Combinado",
            "time": "08:00",
            "unread": 0,
            "last_from_me": True,
        },
    ],
    "open_chat_messages": [
        {"chat": "Ana", "time": "09:12", "author": "Ana", "text": "Oi!"},
    ],
}


class FakeSocket:
    def __init__(self, contexts, page=PAGE, errors=()):
        self.contexts, self.page, self.errors = contexts, page, set(errors)
        self.sent, self._replies = [], []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        method = msg["method"]
        if method in self.errors:
            reply = {"id": msg["id"], "type": "error", "error": "session not created"}
        elif method == "browsingContext.getTree":
            reply = {
                "id": msg["id"],
                "type": "success",
                "result": {"contexts": self.contexts},
            }
        elif method == "browsingContext.create":
            self.contexts.append({"context": "new", "url": "about:blank"})
            reply = {"id": msg["id"], "type": "success", "result": {"context": "new"}}
        elif method == "script.evaluate":
            reply = {
                "id": msg["id"],
                "type": "success",
                "result": {
                    "type": "success",
                    "result": {"type": "string", "value": json.dumps(self.page)},
                },
            }
        else:
            reply = {"id": msg["id"], "type": "success", "result": {}}
        self._replies += [{"type": "event", "method": "log.entryAdded"}, reply]

    def recv(self, timeout=None):
        return json.dumps(self._replies.pop(0))


def client_for(socket, **kwargs):
    return WhatsAppWebClient(
        "ws://fake/session",
        connector=lambda *a, **k: socket,
        sleep=lambda s: None,
        **kwargs,
    )


TABS = [
    {"context": "a", "url": "https://example.com/"},
    {"context": "w", "url": "https://web.whatsapp.com/"},
]


def test_reads_whatsapp_tab_in_sandbox_and_ends_session():
    socket = FakeSocket(TABS)
    result = client_for(socket).today()

    assert result["status"] == "ok"
    assert result["unread_total"] == 2
    assert result["open_chat_messages_today"][0]["text"] == "Oi!"
    evaluate = next(m for m in socket.sent if m["method"] == "script.evaluate")
    assert evaluate["params"]["target"] == {"context": "w", "sandbox": "openjarvis"}
    assert [m["method"] for m in socket.sent][-1] == "session.end"


def test_only_own_messages_today_is_empty():
    page = {**PAGE, "chats": PAGE["chats"][1:], "open_chat_messages": []}
    assert client_for(FakeSocket(TABS, page)).today()["status"] == "empty"


def test_missing_tab_is_opened_and_read():
    socket = FakeSocket(TABS[:1])
    assert client_for(socket).today()["status"] == "ok"
    navigate = next(m for m in socket.sent if m["method"] == "browsingContext.navigate")
    assert navigate["params"]["context"] == "new"
    assert navigate["params"]["url"] == "https://web.whatsapp.com"
    assert socket.sent[-1]["method"] == "session.end"


def test_not_logged_in():
    socket = FakeSocket(TABS, {"logged_in": False})
    with pytest.raises(WhatsAppUnavailable, match="QR code"):
        client_for(socket).today()


def test_bidi_error_is_reported():
    socket = FakeSocket(TABS, errors={"session.new"})
    with pytest.raises(WhatsAppUnavailable, match="session not created"):
        client_for(socket).today()


def refuse(*args, **kwargs):
    raise ConnectionRefusedError


def test_running_firefox_without_port_is_left_alone():
    launched = []
    client = WhatsAppWebClient(
        "ws://127.0.0.1:9222/session",
        connector=refuse,
        launcher=launched.append,
        firefox_running=lambda: True,
    )
    with pytest.raises(WhatsAppUnavailable, match="--remote-debugging-port 9222"):
        client.today()
    assert launched == []


def test_closed_firefox_is_started_with_debug_port_then_read():
    launched, attempts = [], []
    socket = FakeSocket(TABS)

    def connector(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionRefusedError
        return socket

    client = WhatsAppWebClient(
        "ws://127.0.0.1:9333/session",
        connector=connector,
        launcher=launched.append,
        firefox_running=lambda: False,
        sleep=lambda s: None,
    )
    assert client.today()["status"] == "ok"
    assert launched == [9333]


def test_started_firefox_that_never_listens_reports_port():
    client = WhatsAppWebClient(
        "ws://127.0.0.1:9222/session",
        connector=refuse,
        launcher=lambda port: None,
        firefox_running=lambda: False,
        sleep=lambda s: None,
        launch_timeout=0,
    )
    with pytest.raises(WhatsAppUnavailable, match="9222 não respondeu"):
        client.today()


def test_tool_registered_and_reports_unavailable():
    import importlib

    import openjarvis.tools.whatsapp_web as module

    importlib.reload(module)
    assert ToolRegistry.get("whatsapp_today") is module.WhatsAppTodayTool

    class Broken:
        def today(self):
            raise WhatsAppUnavailable("sem Firefox")

    result = WhatsAppTodayTool(Broken()).execute()
    assert result.success is False
    assert json.loads(result.content) == {
        "status": "unavailable",
        "message": "sem Firefox",
    }
