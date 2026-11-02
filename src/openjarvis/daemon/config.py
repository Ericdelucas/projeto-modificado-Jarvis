"""Explicit dotenv configuration. Never loads OpenJarvis/Ollama configuration."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DaemonConfig:
    model: str
    api_key: str = field(repr=False)
    base_url: str = "https://api.openai.com/v1"
    min_available_mb: int = 1536
    max_steps: int = 10
    timeout: float = 120
    request_timeout: float = 25
    headless: bool = False

    def __post_init__(self):
        url = urlsplit(self.base_url)
        host = url.hostname or ""
        try:
            local = not ipaddress.ip_address(host).is_global
        except ValueError:
            local = host == "localhost" or host.endswith((".localhost", ".local"))
        if (
            url.scheme != "https"
            or not host
            or local
            or url.port == 11434
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Configure uma API HTTPS remota, sem credenciais na URL.")
        if (
            not isinstance(self.model, str)
            or not isinstance(self.api_key, str)
            or not self.model.strip()
            or not self.api_key.strip()
        ):
            raise ValueError(
                "Defina JARVIS_CORE_MODEL e JARVIS_CORE_API_KEY no arquivo de ambiente."
            )
        if not 1 <= self.max_steps <= 10:
            raise ValueError("JARVIS_CORE_MAX_STEPS deve estar entre 1 e 10.")
        if not 1 <= self.timeout <= 300 or not 1 <= self.request_timeout <= 60:
            raise ValueError("Prazos inválidos: tarefa <=300s e requisição <=60s.")

    @classmethod
    def from_env(cls, env_file=None):
        values = {}
        if env_file is not None:
            from dotenv import dotenv_values

            path = Path(env_file)
            if not path.is_file():
                raise ValueError("Arquivo de ambiente informado não existe.")
            values.update(dotenv_values(path, interpolate=False))
        values.update(os.environ)  # Explicit environment wins; secrets never logged.
        return cls(
            model=values.get("JARVIS_CORE_MODEL", ""),
            api_key=values.get("JARVIS_CORE_API_KEY", ""),
            base_url=values.get("JARVIS_CORE_BASE_URL", "https://api.openai.com/v1"),
            min_available_mb=int(values.get("JARVIS_CORE_MIN_AVAILABLE_MB", "1536")),
            max_steps=int(values.get("JARVIS_CORE_MAX_STEPS", "10")),
            timeout=float(values.get("JARVIS_CORE_TIMEOUT", "120")),
            request_timeout=float(values.get("JARVIS_CORE_REQUEST_TIMEOUT", "25")),
            headless=values.get("JARVIS_CORE_HEADLESS", "false").lower() == "true",
        )
