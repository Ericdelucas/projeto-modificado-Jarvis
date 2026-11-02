"""Cheap intent classification and per-request routing, with bounded RAG."""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from .config import ProgramacaoConfig
from .rag_books import BooksRag

logger = logging.getLogger(__name__)


def programming_intent(text: str) -> bool:
    from openjarvis.operators.gui_operator import browser_search_intent

    if browser_search_intent(text) is not None:
        return False  # Navigation is a system action, regardless of query topic.
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    # Opening an IDE/browser remains a system action, not a coding task.
    if re.match(
        r"\s*(?:por favor[, ]+)?(?:abra|abre|abrir|inicie|iniciar|open|launch)\s+",
        normalized,
    ):
        return False
    if "```" in text or re.search(r"\b(?:def\s+\w+\(|class\s+\w+[:(])", text):
        return True
    return bool(
        re.search(
            r"\b(?:codigo|code|python|fastapi|javascript|typescript|java|rust|sql|"
            r"react|django|flask|api|backend|frontend|refator\w*|debug\w*|depur\w*|script|funcao|"
            r"function|algoritmo|programa[cç]ao|programming|traceback|unittest|"
            r"arquitetura de software|engenharia de software)\b",
            normalized,
        )
        or re.search(
            r"\b(?:erro|error|bug|arquitetura)\b.*\b"
            r"(?:api|backend|frontend|servidor|software|compil\w*|teste\w*|modulo)\b",
            normalized,
        )
    )


class ModelAvailability:
    def __init__(self):
        self.lock = threading.Lock()
        self.models: set[str] = set()
        self.expires = 0.0

    def get(self, engine) -> set[str]:
        with self.lock:
            if time.monotonic() >= self.expires:
                self.models = set(engine.list_models())
                self.expires = time.monotonic() + 10
            return self.models


@lru_cache(maxsize=4)
def _availability(host: str) -> ModelAvailability:
    return ModelAvailability()


@lru_cache(maxsize=4)
def _retriever(config_items: tuple, host: str):
    cfg = ProgramacaoConfig(**dict(config_items))
    return BooksRag(cfg, host), threading.Lock()


@dataclass(frozen=True)
class ProgrammingRoute:
    model: str
    context: str = ""
    programming: bool = False


def prepare_route(text: str, requested_model: str, config, engine) -> ProgrammingRoute:
    cfg = getattr(config, "programacao", None)
    backend = engine
    for _ in range(4):
        kind = getattr(backend, "engine_id", None)
        if kind == "instrumented":
            backend = backend._inner
        elif kind == "multi":
            backend = next(
                (inner for key, inner in backend._engines if key == "ollama"),
                None,
            )
        else:
            break
    if (
        not isinstance(cfg, ProgramacaoConfig)
        or not cfg.enabled
        or getattr(backend, "engine_id", None) != "ollama"
    ):
        return ProgrammingRoute(requested_model)
    cfg.validate()
    if not programming_intent(text):
        return ProgrammingRoute(cfg.general_model)
    host = config.engine.ollama.host
    model = cfg.general_model
    try:
        models = _availability(host).get(backend)
        candidates = (cfg.code_model, f"{cfg.code_model}:latest")
        model = next((item for item in candidates if item in models), model)
        if model == cfg.general_model:
            logger.warning(
                "Programming model %s unavailable; using %s",
                cfg.code_model,
                model,
            )
    except Exception:
        logger.warning("Cannot list local code models; using %s", model, exc_info=True)
    context = ""
    if cfg.rag_enabled:
        try:
            from dataclasses import asdict

            rag, lock = _retriever(tuple(asdict(cfg).items()), host)
            with lock:
                context = rag.context(text)
        except Exception:
            # Missing index/dependencies/Ollama must not break the normal chat.
            logger.warning(
                "Technical-book RAG unavailable; continuing without it", exc_info=True
            )
    logger.info("Programming route: model=%s reference_chars=%d", model, len(context))
    return ProgrammingRoute(model, context, True)
