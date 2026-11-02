"""Wake-word lifecycle, ownership, pause and SSE delivery without a microphone."""

import asyncio
import json
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from openjarvis.server.wakeword_routes import events, router
from openjarvis.speech.wakeword import WakeWordService


def test_exact_word_cooldown_and_busy_guard():
    service = WakeWordService()
    service.enabled = True
    with patch.object(service, "_publish") as publish:
        assert not service.detect("computadores", 100)
        assert service.detect("oi computador", 100)
        assert not service.detect("computador", 101)
        service._busy = True
        assert not service.detect("computador", 105)
        service._busy = False
        assert service.detect("computador", 106)
        service.stop()
        assert not service.detect("computador", 120)
        assert (
            sum(call.args[0]["kind"] == "wake" for call in publish.call_args_list) == 2
        )


@pytest.mark.asyncio
async def test_only_owner_receives_activation_and_disconnect_stops_listener():
    service = WakeWordService()
    owner, other = asyncio.Queue(), asyncio.Queue()
    service.subscribe("owner", "a", owner)
    service.subscribe("other", "b", other)
    service.enabled = True
    service.owner_id = "owner"
    assert service.detect("computador", 100)
    await asyncio.sleep(0)
    assert (await owner.get())["kind"] == "wake"
    assert other.empty()
    service.unsubscribe("a")
    assert not service.enabled
    service.unsubscribe("b")


@pytest.mark.parametrize(
    "confidence, expected", [(0.95, True), (0.7, True), (0.4, False), (None, True)]
)
def test_worker_uses_local_frames_and_resets_after_detection(confidence, expected):
    service = WakeWordService()
    recognizer = MagicMock()
    recognizer.AcceptWaveform.return_value = False
    payload = {"partial": "computador"}
    if confidence is not None:
        payload["partial_result"] = [{"word": "computador", "conf": confidence}]
    recognizer.PartialResult.return_value = json.dumps(payload)
    reads = 0

    @contextmanager
    def capture():
        def read():
            nonlocal reads
            reads += 1
            if reads > 3:
                service._stop.set()
            return b"\0" * 2560

        yield read

    service.enabled = True
    service._heartbeat = time.monotonic()
    with (
        patch("vosk.Model"),
        patch("vosk.KaldiRecognizer", return_value=recognizer) as factory,
        patch.object(service, "_capture", capture),
        patch.object(service, "_publish") as publish,
    ):
        service._run()
    assert (
        any(call.args[0]["kind"] == "wake" for call in publish.call_args_list)
        == expected
    )
    assert recognizer.Reset.called == expected
    assert json.loads(factory.call_args_list[0].args[2]) == ["computador", "[unk]"]
    assert not service.enabled


@pytest.mark.parametrize(
    "confidence, frames, expected",
    [(0.7, 8, False), (0.85, 8, True), (None, 4, False), (None, 8, True)],
)
def test_stricter_threshold_and_stable_frames(confidence, frames, expected):
    service = WakeWordService(threshold=0.8, stable_frames=6)
    recognizer = MagicMock()
    recognizer.AcceptWaveform.return_value = False
    payload = {"partial": "computador"}
    if confidence is not None:
        payload["partial_result"] = [{"word": "computador", "conf": confidence}]
    recognizer.PartialResult.return_value = json.dumps(payload)
    reads = 0

    @contextmanager
    def capture():
        def read():
            nonlocal reads
            reads += 1
            if reads > frames:
                service._stop.set()
            return b"\0" * 2560

        yield read

    service.enabled = True
    service._heartbeat = time.monotonic()
    with (
        patch("vosk.Model"),
        patch("vosk.KaldiRecognizer", return_value=recognizer),
        patch.object(service, "_capture", capture),
        patch.object(service, "_publish") as publish,
    ):
        service._run()
    assert (
        any(call.args[0]["kind"] == "wake" for call in publish.call_args_list)
        == expected
    )


@pytest.mark.asyncio
async def test_control_validation_and_heartbeat():
    service = WakeWordService()
    service.owner_id = "owner"
    app = FastAPI()
    app.state.wakeword_service = service
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/wakeword/status")).json()["word"] == "computador"
        assert (
            await client.post(
                "/api/wakeword/control", json={"client_id": "other", "enabled": False}
            )
        ).status_code == 409
        assert (
            await client.post(
                "/api/wakeword/heartbeat", json={"client_id": "owner", "busy": True}
            )
        ).status_code == 200
        assert service._busy
        with patch.object(
            service, "enable", side_effect=RuntimeError("Modelo ausente")
        ):
            assert (
                await client.post(
                    "/api/wakeword/control",
                    json={"client_id": "owner", "enabled": True},
                )
            ).status_code == 503


@pytest.mark.asyncio
async def test_sse_initial_status_and_activation():
    app = FastAPI()
    service = WakeWordService()
    app.state.wakeword_service = service
    request = Request(
        {"type": "http", "app": app, "method": "GET", "path": "/", "headers": []}
    )
    request.is_disconnected = MagicMock(side_effect=None)

    async def connected():
        return False

    request.is_disconnected = connected
    response = await events(request, "owner")
    iterator = response.body_iterator
    try:
        assert '"kind": "status"' in await iterator.__anext__()
        service.enabled = True
        service.owner_id = "owner"
        service.detect("computador", 100)
        assert '"kind": "wake"' in await iterator.__anext__()
    finally:
        await iterator.aclose()
    assert not service.enabled


@pytest.mark.parametrize("text", ["computador", "Computer!", "oi, computador."])
def test_aliases_accept_whole_words(text):
    service = WakeWordService()
    service.enabled = True
    with patch.object(service, "_publish"):
        assert service.detect(text, 100)


def test_rms_and_telemetry_report_received_and_processed_frames():
    from array import array

    from openjarvis.speech.wakeword import audio_level

    pcm = array("h", [16384] * 1280).tobytes()
    rms, dbfs = audio_level(pcm)
    assert rms == pytest.approx(0.5)
    assert dbfs == pytest.approx(-6.02, abs=0.01)
    assert audio_level(b"\0" * 2560) == (0, -96)
    service = WakeWordService()
    with patch.object(service, "_publish") as publish:
        service._audio_diagnostics(pcm, 100, "tts")
    event = publish.call_args.args[0]
    assert event["kind"] == "telemetry"
    assert event["frames"] == 1
    assert event["audio_bytes"] == 2560
    assert event["processed_frames"] == 0
    assert event["paused_reason"] == "tts"
