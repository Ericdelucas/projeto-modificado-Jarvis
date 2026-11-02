"""Web voice output with a fixed Brazilian Portuguese neural voice."""

import asyncio
import importlib.util
import logging

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from openjarvis.speech.edge_voice import (
    PITCH,
    RATE,
    VOICE,
    clean_speech_text,
    stream_mp3,
    synthesize_mp3,
)

router = APIRouter(prefix="/api/tts", tags=["speech"])
logger = logging.getLogger(__name__)


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.get("/health")
async def health():
    """Report installation status; this does not probe the remote service."""
    return {
        "available": importlib.util.find_spec("edge_tts") is not None,
        "backend": "edge-tts",
        "voice_id": VOICE,
        "rate": RATE,
        "pitch": PITCH,
    }


@router.post("")
async def speak(body: TtsRequest):
    text = clean_speech_text(body.text)
    if not text:
        raise HTTPException(400, "O texto não contém conteúdo para leitura.")
    try:
        audio = await asyncio.wait_for(synthesize_mp3(text), timeout=60)
    except ImportError as exc:
        raise HTTPException(
            503, "Instale edge-tts para habilitar a voz neural."
        ) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, "O serviço de voz demorou para responder.") from exc
    except Exception as exc:
        logger.exception("Edge TTS synthesis failed")
        raise HTTPException(
            502, "Não foi possível gerar a voz. Verifique a conexão com a internet."
        ) from exc
    return Response(
        audio,
        media_type="audio/mpeg",
        headers={"X-Voice-Id": VOICE, "Cache-Control": "no-store"},
    )


@router.post("/stream")
async def speak_stream(body: TtsRequest):
    """Send the first MP3 chunk immediately instead of collecting the whole clip."""
    text = clean_speech_text(body.text)
    if not text:
        raise HTTPException(400, "O texto não contém conteúdo para leitura.")
    source = stream_mp3(text)
    try:
        first = await asyncio.wait_for(source.__anext__(), timeout=30)
    except Exception as exc:
        await source.aclose()
        logger.exception("Edge TTS stream could not start")
        raise HTTPException(502, "Não foi possível iniciar a voz neural.") from exc

    async def audio():
        try:
            yield first
            while True:
                try:
                    yield await asyncio.wait_for(source.__anext__(), timeout=30)
                except StopAsyncIteration:
                    break
        finally:
            await source.aclose()

    return StreamingResponse(
        audio(),
        media_type="audio/mpeg",
        headers={
            "X-Voice-Id": VOICE,
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
