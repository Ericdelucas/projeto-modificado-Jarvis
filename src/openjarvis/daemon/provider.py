"""Asynchronous OpenAI-compatible HTTP API; no engine or model loaders."""

from __future__ import annotations

import json

import httpx


class RemotePlanner:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or httpx.AsyncClient(
            timeout=config.request_timeout,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        self.owns_client = client is None

    async def decide(self, prompt, payload, image=None):
        content = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
        if image:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64," + image,
                        "detail": "low",
                    },
                }
            )
        request = {
            "model": self.config.model,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
        }
        raw = bytearray()
        try:
            async with self.client.stream(
                "POST",
                self.config.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + self.config.api_key},
                json=request,
            ) as response:
                if response.status_code != 200:
                    # Do not expose response bodies, credentials, screenshots or URLs.
                    raise RuntimeError(
                        f"API remota respondeu HTTP {response.status_code}."
                    )
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 128 * 1024:
                        raise ValueError("Resposta remota excedeu 128 KiB.")
                    raw.extend(chunk)
            data = json.loads(raw)
            result = json.loads(data["choices"][0]["message"]["content"])
            if not isinstance(result, dict):
                raise ValueError("A decisão remota deve ser um objeto JSON.")
            return result
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Falha de comunicação ou resposta inválida da API remota."
            ) from exc
        finally:
            raw.clear()
            content.clear()
            request.clear()
            image = None

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
