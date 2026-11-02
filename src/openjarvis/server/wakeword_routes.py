"""Authenticated control and SSE events for the local wake-word worker."""

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/wakeword", tags=["speech"])


class Control(BaseModel):
    enabled: bool
    client_id: str = Field(min_length=1, max_length=100)


class Heartbeat(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)
    busy: bool
    reason: str | None = Field(default=None, max_length=50)


@router.get("/status")
async def status(request: Request):
    return request.app.state.wakeword_service.status()


@router.post("/control")
async def control(body: Control, request: Request):
    service = request.app.state.wakeword_service
    async with service.control_lock:
        if not body.enabled and service.owner_id not in {None, body.client_id}:
            raise HTTPException(409, "A escuta está sendo usada em outra aba.")
        try:
            return (
                await asyncio.to_thread(service.enable, body.client_id)
                if body.enabled
                else await asyncio.to_thread(service.stop)
            )
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc


@router.post("/heartbeat")
async def heartbeat(body: Heartbeat, request: Request):
    request.app.state.wakeword_service.heartbeat(body.client_id, body.busy, body.reason)
    return {"ok": True}


@router.get("/events")
async def events(request: Request, client_id: str):
    if not client_id or len(client_id) > 100:
        raise HTTPException(400, "Cliente inválido.")
    service = request.app.state.wakeword_service

    async def stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        key = uuid.uuid4().hex
        service.subscribe(client_id, key, queue)
        try:
            yield f"data: {json.dumps({'kind': 'status', **service.status()})}\n\n"
            while not await request.is_disconnected():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=5)
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            # StreamingResponse cancels its task on disconnect. Remove the
            # subscription synchronously so cancellation cannot skip cleanup.
            # stop(wait=False) signals the worker without joining on this loop.
            service.unsubscribe(key)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
