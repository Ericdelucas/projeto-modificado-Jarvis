"""Thread-safe emergency stop, ten-action cap and independent RAM watchdog."""

from __future__ import annotations

import asyncio
import contextlib
import threading

import psutil


class SafetyStop(RuntimeError):
    """Latched interruption; no more actions may be dispatched."""


class SafetyGuard:
    def __init__(self, min_available_mb=1536, max_steps=10, memory=None):
        self.min_available_mb = max(256, int(min_available_mb))
        self.max_steps = max(1, min(10, int(max_steps)))
        self.memory = memory or psutil.virtual_memory
        self.stopped = threading.Event()
        self.finished = threading.Event()
        self.reason = ""
        self.steps = 0
        self.thread = None
        self._lock = threading.Lock()

    def stop(self, reason="Parada de emergência solicitada."):
        with self._lock:
            if not self.stopped.is_set():
                self.reason = reason
                self.stopped.set()

    def check(self):
        if self.memory().available < self.min_available_mb * 1024 * 1024:
            self.stop("RAM em nível crítico; execução interrompida.")
        if self.stopped.is_set():
            raise SafetyStop(self.reason)

    def before_action(self):
        self.check()
        if self.steps >= self.max_steps:
            self.stop("Limite de 10 ações (ou limite menor configurado) atingido.")
            raise SafetyStop(self.reason)
        self.steps += 1

    def start(self):
        self.check()

        def watch():
            while not self.finished.wait(0.05):
                try:
                    self.check()
                except Exception:
                    self.stop("Falha no monitor de segurança.")
                    return

        self.thread = threading.Thread(
            target=watch, daemon=True, name="jarvis-core-safety"
        )
        self.thread.start()

    async def wait(self, awaitable):
        """Cancel remote I/O promptly; native operations see the shared stop flag."""
        future = asyncio.ensure_future(awaitable)
        try:
            while True:
                self.check()
                done, _ = await asyncio.wait({future}, timeout=0.05)
                if done:
                    self.check()
                    return future.result()
        except BaseException:
            future.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await future
            raise

    @contextlib.asynccontextmanager
    async def time_limit(self, seconds):
        """Signal the same stop latch on timeout, including on Python 3.10."""
        timer = asyncio.get_running_loop().call_later(
            seconds, self.stop, "Tempo máximo atingido."
        )
        try:
            yield
        finally:
            timer.cancel()

    def close(self):
        self.finished.set()
        if self.thread:
            self.thread.join(timeout=0.2)
