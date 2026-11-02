from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from openjarvis.daemon.backends import DesktopBackend, WebBackend
from openjarvis.daemon.config import DaemonConfig
from openjarvis.daemon.controller import JarvisCoreDaemon
from openjarvis.daemon.provider import RemotePlanner
from openjarvis.daemon.safety_guardrails import SafetyGuard, SafetyStop


def config(**kwargs):
    return DaemonConfig(
        model="remote-vision-test",
        api_key="test-not-real",
        base_url="https://vision.example/v1",
        **kwargs,
    )


def guard_factory():
    return SafetyGuard(memory=lambda: SimpleNamespace(available=16 * 1024**3))


class Backend:
    def __init__(self, guard):
        self.guard = guard
        self.actions = []
        self.threads = []
        self.closed = False

    def start(self):
        self.threads.append(threading.get_ident())

    def observe(self):
        self.threads.append(threading.get_ident())
        return {
            "url": "https://example.org/result",
            "text": "Objetivo confirmado",
        }, None

    def act(self, action):
        self.guard.check()
        self.threads.append(threading.get_ident())
        self.actions.append(action)

    def close(self):
        self.threads.append(threading.get_ident())
        self.closed = True


def setup_daemon(tmp_path, decisions, **kwargs):
    planner = SimpleNamespace(
        decide=AsyncMock(side_effect=decisions), close=AsyncMock()
    )
    backends = []

    def factory(mode, guard):
        backend = Backend(guard)
        backends.append(backend)
        return backend

    daemon = JarvisCoreDaemon(
        config(),
        planner=planner,
        backend_factory=factory,
        guard_factory=guard_factory,
        runtime_dir=tmp_path,
        **kwargs,
    )
    return daemon, planner, backends


@pytest.mark.asyncio
async def test_remote_dom_loop_and_thread_affinity(tmp_path):
    daemon, planner, backends = setup_daemon(
        tmp_path,
        [
            {"mode": "web"},
            {"action": "navigate", "url": "https://example.org"},
            {"action": "click", "ref": "e1"},
            {"action": "done", "message": "Confirmado"},
            {"complete": True, "evidence": "Objetivo confirmado"},
        ],
    )
    async with daemon:
        result = await daemon.run("Pesquise um tema inédito e abra o resultado")
    assert result["status"] == "completed"
    backend = backends[0]
    assert len(backend.actions) == 2 and backend.closed
    assert len(set(backend.threads)) == 1
    assert backend.threads[0] != threading.get_ident()
    assert all(
        len(call.args) < 3 or call.args[2] is None
        for call in planner.decide.call_args_list
    )


@pytest.mark.asyncio
async def test_ten_action_cap_never_executes_eleven(tmp_path):
    daemon, planner, backends = setup_daemon(tmp_path, [{"action": "wait"}] * 11)
    async with daemon:
        result = await daemon.run("Continue indefinidamente", "web")
    assert result["status"] == "stopped"
    assert len(backends[0].actions) == 10
    assert backends[0].closed


@pytest.mark.asyncio
async def test_opening_alone_is_not_success(tmp_path):
    daemon, _, backends = setup_daemon(tmp_path, [{"action": "done"}])
    async with daemon:
        result = await daemon.run("Abra e pesquise algo", "web")
    assert result["status"] == "failed"
    assert not backends[0].actions


@pytest.mark.asyncio
async def test_failed_execution_latches_stop_without_retry(tmp_path):
    daemon, planner, backends = setup_daemon(
        tmp_path, [{"action": "click", "ref": "e1"}]
    )
    original = daemon.backend_factory

    def factory(mode, guard):
        backend = original(mode, guard)
        backend.act = MagicMock(side_effect=RuntimeError("Falha de foco."))
        return backend

    daemon.backend_factory = factory
    async with daemon:
        result = await daemon.run("Clique", "web")
    assert result["status"] == "failed"
    assert planner.decide.await_count == 1
    assert backends[0].guard.stopped.is_set() and backends[0].closed


@pytest.mark.asyncio
async def test_critical_ram_prevents_backend_and_network(tmp_path):
    daemon, planner, backends = setup_daemon(tmp_path, [])
    daemon.guard_factory = lambda: SafetyGuard(
        memory=lambda: SimpleNamespace(available=0)
    )
    async with daemon:
        result = await daemon.run("Teste", "web")
    assert result["status"] == "stopped"
    assert not backends
    planner.decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_ram_watchdog_cancels_pending_remote_call(tmp_path):
    daemon, planner, backends = setup_daemon(tmp_path, [])
    memory = SimpleNamespace(available=16 * 1024**3)
    daemon.guard_factory = lambda: SafetyGuard(memory=lambda: memory)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def pending(*args):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    planner.decide.side_effect = pending
    async with daemon:
        task = asyncio.create_task(daemon.run("Teste", "web"))
        await asyncio.wait_for(started.wait(), 2)
        memory.available = 0
        result = await asyncio.wait_for(task, 2)
    assert result["status"] == "stopped"
    assert cancelled.is_set() and not backends[0].actions


@pytest.mark.asyncio
async def test_emergency_stop_is_responsive_while_api_waits(tmp_path):
    daemon, planner, backends = setup_daemon(tmp_path, [])
    started = asyncio.Event()

    async def pending(*args):
        started.set()
        await asyncio.sleep(60)

    planner.decide.side_effect = pending
    async with daemon:
        task = asyncio.create_task(daemon.run("Teste", "web"))
        await asyncio.wait_for(started.wait(), 2)
        assert (await daemon.run("Outra tarefa", "web"))["status"] == "blocked"
        daemon.stop()
        assert (await asyncio.wait_for(task, 2))["status"] == "stopped"
    assert not backends[0].actions


def test_desktop_mouse_stops_mid_move():
    guard = guard_factory()
    backend = DesktopBackend(config(), guard)
    pg = MagicMock()
    pg.position.return_value = (100, 100)

    def moved(*args, **kwargs):
        if pg.moveTo.call_count == 3:
            guard.stop()

    pg.moveTo.side_effect = moved
    backend.gui = SimpleNamespace(
        control=contextlib.nullcontext,
        backend=lambda: pg,
        focus=lambda app: None,
        check=guard.check,
    )
    backend.target = "Editor"
    backend.frame_size = (960, 640)
    backend.screen_size = (1920, 1280)
    with pytest.raises(SafetyStop):
        backend.act({"action": "click", "x": 200, "y": 100})
    assert pg.moveTo.call_count == 3
    pg.click.assert_not_called()


def test_web_never_uses_coordinates_or_screenshots():
    backend = WebBackend(config(), guard_factory())
    backend.session = MagicMock()
    backend.session.observe.return_value = {"url": "https://example.org"}
    assert backend.observe()[1] is None
    with pytest.raises(ValueError, match="DOM"):
        backend.act({"action": "click", "x": 10, "y": 20})
    backend.session.capture_frame.assert_not_called()
    backend.session.act.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "http://vision.example",
        "https://127.0.0.1:11434/v1",
        "https://localhost/v1",
        "https://192.168.0.1/v1",
        "https://user:secret@vision.example/v1",
    ],
)
def test_configuration_rejects_local_inference_and_insecure_urls(url):
    with pytest.raises(ValueError):
        DaemonConfig("vision", "test", base_url=url)


def test_dotenv_file_and_environment_precedence(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text('JARVIS_CORE_MODEL="vision-env"\nJARVIS_CORE_API_KEY="test"\n')
    monkeypatch.setenv("JARVIS_CORE_MODEL", "vision-override")
    cfg = DaemonConfig.from_env(path)
    assert cfg.model == "vision-override"
    assert "api_key=" not in repr(cfg)


@pytest.mark.asyncio
async def test_remote_http_protocol_and_image_release():
    requests = []

    async def handler(request):
        assert request.url.host == "vision.example"
        data = json.loads(request.content)
        requests.append(data)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"action":"click","x":20,"y":40}'}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        planner = RemotePlanner(config(), client=client)
        result = await planner.decide("Only JSON", {"task": "Click"}, "jpeg-test")
    assert result["action"] == "click"
    image = requests[0]["messages"][1]["content"][1]["image_url"]
    assert image == {"url": "data:image/jpeg;base64,jpeg-test", "detail": "low"}
    assert requests[0]["max_tokens"] == 512


@pytest.mark.asyncio
async def test_api_errors_do_not_leak_secrets():
    async def handler(request):
        return httpx.Response(401, text="secret-api-key-and-screen-data")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        planner = RemotePlanner(config(), client=client)
        with pytest.raises(RuntimeError, match="HTTP 401") as error:
            await planner.decide("JSON", {"task": "test"})
    assert "secret-api-key" not in str(error.value)


def test_import_does_not_load_local_inference():
    code = (
        "import sys; from openjarvis.daemon.controller import JarvisCoreDaemon; "
        'assert "openjarvis.engine.ollama" not in sys.modules; '
        'assert "torch" not in sys.modules'
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


@pytest.mark.asyncio
async def test_real_firefox_with_remote_transport(tmp_path, monkeypatch):
    import os
    from urllib.parse import parse_qs, urlsplit

    if os.environ.get("RUN_BROWSER_INTEGRATION") != "1":
        pytest.skip("Set RUN_BROWSER_INTEGRATION=1 to launch real Firefox")
    from openjarvis.operators import browser_operator

    original_session = browser_operator.BrowserSession
    monkeypatch.setattr(
        browser_operator,
        "BrowserSession",
        lambda **kwargs: original_session(headless=True, profile=tmp_path / "firefox"),
    )
    phrase = "Fundação Escola de Comércio Álvares Penteado FECAP"
    queries = []
    backend_instances = []

    def serve(route):
        parsed = urlsplit(route.request.url)
        if parsed.path == "/search":
            queries.append(parse_qs(parsed.query)["q"][0])
            html = '<a href="/official">Site oficial</a>'
        elif parsed.path == "/official":
            html = "<title>FECAP oficial</title><h1>" + phrase + "</h1>"
        else:
            html = (
                '<form action="/search"><input name="q"><button>Buscar</button></form>'
            )
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

    cfg = config(headless=True)

    def factory(mode, guard):
        assert mode == "web"
        backend = WebBackend(cfg, guard)
        start = backend.start

        def seeded_start():
            start()
            backend.session.context.route("https://fixture.test/**", serve)
            backend.session.page.goto("https://fixture.test/")
            backend.session.capture_frame = MagicMock(
                side_effect=AssertionError("Web must use DOM")
            )

        backend.start = seeded_start
        backend_instances.append(backend)
        return backend

    decisions = iter(
        [
            {"action": "fill", "ref": "e1", "text": phrase},
            {"action": "press", "ref": "e1", "key": "Enter"},
            {"action": "click", "ref": "e1"},
            {"action": "done", "message": "Site oficial aberto"},
            {"complete": True, "evidence": phrase},
        ]
    )

    async def remote(request):
        assert request.url.host == "vision.example"
        payload = json.loads(request.content)
        parts = payload["messages"][1]["content"]
        assert all(part["type"] == "text" for part in parts)
        decision = next(decisions)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(decision)}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        planner = RemotePlanner(cfg, client)
        async with JarvisCoreDaemon(
            cfg,
            planner=planner,
            backend_factory=factory,
            guard_factory=guard_factory,
            runtime_dir=tmp_path / "runtime",
        ) as core:
            result = await core.run(
                "Pesquise " + phrase + " e abra o site oficial", "web"
            )
    assert result["status"] == "completed", result
    assert result["url"] == "https://fixture.test/official"
    assert queries == [phrase]
    assert len(result["steps"]) == 3
    backend_instances[0].session.capture_frame.assert_not_called()


@pytest.mark.asyncio
async def test_remote_response_size_is_bounded():
    async def handler(request):
        return httpx.Response(200, content=b"x" * (128 * 1024 + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        planner = RemotePlanner(config(), client)
        with pytest.raises(ValueError, match="128 KiB"):
            await planner.decide("JSON", {"task": "test"})


def test_desktop_capture_is_small_and_original_is_closed():
    import base64
    import io

    from PIL import Image

    original = Image.new("RGB", (1920, 1080))
    backend = DesktopBackend(config(), guard_factory())
    backend.gui = SimpleNamespace(
        backend=lambda: SimpleNamespace(screenshot=lambda: original),
        windows=lambda: [{"title": "Editor"}] * 100,
    )
    observation, encoded = backend.observe()
    assert len(observation["windows"]) == 30
    assert len(base64.b64decode(encoded)) <= 512 * 1024
    with io.BytesIO(base64.b64decode(encoded)) as buffer, Image.open(buffer) as decoded:
        assert decoded.width <= 960 and decoded.height <= 640
    with pytest.raises(ValueError):
        original.getpixel((0, 0))


def test_wayland_native_controls_fail_explicitly(monkeypatch):
    monkeypatch.setattr("openjarvis.operators.gui_operator.wayland", lambda: True)
    backend = DesktopBackend(config(), guard_factory())
    with pytest.raises(RuntimeError, match="Wayland"):
        backend.start()
    assert backend.gui is None


@pytest.mark.asyncio
async def test_deadline_stops_remote_wait(tmp_path):
    daemon, planner, backends = setup_daemon(tmp_path, [])
    daemon.config = config(timeout=1)

    async def pending(*args):
        await asyncio.sleep(60)

    planner.decide.side_effect = pending
    async with daemon:
        result = await asyncio.wait_for(daemon.run("Teste", "web"), 3)
    assert result["status"] == "stopped"
    assert "Tempo máximo" in result["message"]
    assert not backends[0].actions
