"""Neural pt-BR voice routes and Markdown cleanup, without remote calls."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from openjarvis.server.tts_routes import router
from openjarvis.speech.edge_voice import VOICE, clean_speech_text, synthesize_mp3


def test_cleans_markdown_without_losing_accents():
    text = (
        "# Olá!\n**Você** pode ver [aqui](https://example.com).\n- Ação\n"
        "```python\nprint(1)\n```\n<think>segredo</think>"
    )
    assert clean_speech_text(text) == "Olá! Você pode ver aqui. Ação"


@pytest.mark.asyncio
async def test_route_returns_mp3_and_fixed_voice():
    app = FastAPI()
    app.include_router(router)
    with patch(
        "openjarvis.server.tts_routes.synthesize_mp3",
        new_callable=AsyncMock,
        return_value=b"mp3-audio",
    ) as synth:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/tts", json={"text": "# Olá **Brasil**!"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["x-voice-id"] == VOICE
    assert response.content == b"mp3-audio"
    synth.assert_awaited_once_with("Olá Brasil!")


@pytest.mark.asyncio
async def test_rejects_empty_and_reports_remote_failure():
    app = FastAPI()
    app.include_router(router)
    with patch(
        "openjarvis.server.tts_routes.synthesize_mp3",
        new_callable=AsyncMock,
        side_effect=RuntimeError("offline"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.post("/api/tts", json={"text": "** **"})
            ).status_code == 400
            assert (
                await client.post("/api/tts", json={"text": "Olá"})
            ).status_code == 502
            assert (
                await client.post("/api/tts", json={"text": "a" * 5001})
            ).status_code == 422


@pytest.mark.asyncio
async def test_edge_communicate_uses_antonio_and_audio_chunks_only():
    async def stream():
        yield {"type": "WordBoundary", "text": "Olá"}
        yield {"type": "audio", "data": b"first"}
        yield {"type": "audio", "data": b"second"}

    with patch("edge_tts.Communicate") as communicate:
        communicate.return_value.stream = stream
        assert await synthesize_mp3("Olá") == b"firstsecond"
        communicate.assert_called_once_with(
            "Olá", "pt-BR-AntonioNeural", rate="-5%", pitch="-2Hz", volume="+0%"
        )


def test_removes_emoji_and_adds_breath_at_a_long_clause():
    text = " ".join(["palavra"] * 25) + " mas agora respiramos naturalmente. 🤖😊✨"
    cleaned = clean_speech_text(text)
    assert cleaned.endswith("palavra, mas agora respiramos naturalmente.")
    assert cleaned.count(",") == 1
    assert "🤖" not in cleaned and "😊" not in cleaned


@pytest.mark.asyncio
async def test_stream_route_yields_provider_chunks():
    app = FastAPI()
    app.include_router(router)

    async def chunks(text):
        assert text == "Olá Brasil!"
        yield b"first"
        yield b"second"

    with patch("openjarvis.server.tts_routes.stream_mp3", chunks):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/tts/stream", json={"text": "**Olá Brasil!**"}
            )
    assert response.status_code == 200
    assert response.content == b"firstsecond"
    assert response.headers["x-accel-buffering"] == "no"
