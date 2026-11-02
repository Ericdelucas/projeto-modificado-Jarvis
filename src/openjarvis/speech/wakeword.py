"""Offline Portuguese wake-word listener for the server's local microphone."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
from array import array
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
MODEL_PATH = Path(
    os.environ.get("OPENJARVIS_WAKE_MODEL", ".runtime/wakeword/vosk-model-small-pt-0.3")
)

ALIASES = frozenset({"computador", "computer"})


def audio_level(data: bytes) -> tuple[float, float]:
    samples = array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    rms = (
        math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
        if samples
        else 0.0
    )
    return rms, max(-96.0, 20 * math.log10(max(rms, 1e-8)))


def wake_tokens(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold())) & ALIASES


def diagnostic_log(message: str, *args) -> None:
    if os.environ.get("OPENJARVIS_WAKE_DEBUG", "1") == "0":
        return
    diagnostic = logging.getLogger("openjarvis.wakeword.diagnostics")
    if not diagnostic.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[wakeword] %(message)s"))
        diagnostic.addHandler(handler)
        diagnostic.setLevel(logging.INFO)
        diagnostic.propagate = False
    diagnostic.info(message, *args)


class WakeWordService:
    """One microphone, one owning browser, bounded event queues, no audio storage."""

    def __init__(
        self,
        model_path: Path = MODEL_PATH,
        *,
        threshold: float = 0.65,
        stable_frames: int = 3,
    ):
        self.model_path = model_path
        self._lock = threading.RLock()
        self.control_lock = asyncio.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._audio: Any = None
        self._clients: dict[
            str, tuple[str, asyncio.AbstractEventLoop, asyncio.Queue]
        ] = {}
        self.enabled = False
        self.owner_id: str | None = None
        self.state = "disabled"
        self.error: str | None = None
        self.audio_backend: str | None = None
        self.audio_source: str | None = None
        self._busy = False
        self._busy_reason: str | None = None
        self._heartbeat = 0.0
        self._inhibit_until = 0.0
        self._last_detection = 0.0
        self._model: Any = None
        self._english_model: Any = None
        self.english_path = Path(
            os.environ.get(
                "OPENJARVIS_WAKE_EN_MODEL",
                ".runtime/wakeword/vosk-model-small-en-us-0.15",
            )
        )
        self.threshold = float(os.environ.get("OPENJARVIS_WAKE_THRESHOLD", threshold))
        self.stable_frames = max(1, int(stable_frames))
        if not 0 < self.threshold <= 1:
            raise ValueError("OPENJARVIS_WAKE_THRESHOLD deve estar entre 0 e 1.")
        self.telemetry = {
            "rms": 0.0,
            "dbfs": -96.0,
            "frames": 0,
            "processed_frames": 0,
            "audio_bytes": 0,
            "last_text": "",
            "confidence": 0.0,
            "paused_reason": None,
            "detections": 0,
        }
        self._last_telemetry = 0.0
        self._last_audio_log = 0.0
        self._last_text_log = {}

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "state": self.state,
                "error": self.error,
                "owner_id": self.owner_id,
                "word": "computador",
                "engine": "vosk",
                "model_available": self.model_path.is_dir(),
                "audio_backend": self.audio_backend,
                "audio_source": self.audio_source,
                "aliases": sorted(ALIASES),
                "languages": ["pt"] + (["en"] if self.english_path.is_dir() else []),
                "threshold": self.threshold,
                "subscribers": len(self._clients),
                "diagnostics": dict(self.telemetry),
            }

    def _publish(self, event: dict, owner_only: bool = False) -> None:
        with self._lock:
            clients = list(self._clients.values())
            owner = self.owner_id
        for client, loop, queue in clients:
            if owner_only and client != owner:
                continue

            def put(q=queue, item=event):
                if q.full():
                    q.get_nowait()
                q.put_nowait(item)

            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(put)

    def subscribe(self, client_id: str, key: str, queue: asyncio.Queue) -> None:
        with self._lock:
            self._clients[key] = (client_id, asyncio.get_running_loop(), queue)
        diagnostic_log("SSE conectado cliente=%s", client_id)

    def unsubscribe(self, key: str) -> None:
        with self._lock:
            removed = self._clients.pop(key, None)
            was_owner = removed is not None and removed[0] == self.owner_id
            connected = any(c[0] == self.owner_id for c in self._clients.values())
        diagnostic_log("SSE desconectado chave=%s dono_presente=%s", key, connected)
        if was_owner and not connected:
            self.stop(wait=False)

    def enable(self, client_id: str) -> dict:
        self.stop()
        if not self.model_path.is_dir():
            raise RuntimeError(f"Modelo Vosk ausente: {self.model_path}")
        with self._lock:
            self._stop.clear()
            self.enabled = True
            self.owner_id = client_id
            self.state = "starting"
            self.error = None
            self._busy = False
            self._heartbeat = time.monotonic()
            self._inhibit_until = 0.0
            self._last_detection = 0.0
            self._busy_reason = None
            self.telemetry.update(
                rms=0.0,
                dbfs=-96.0,
                frames=0,
                processed_frames=0,
                audio_bytes=0,
                last_text="",
                confidence=0.0,
                paused_reason=None,
                detections=0,
            )
            self._last_telemetry = self._last_audio_log = 0.0
            self._last_text_log = {}
            diagnostic_log(
                "Iniciando cliente=%s modelo=%s aliases=%s limiar=%.2f",
                client_id,
                self.model_path,
                sorted(ALIASES),
                self.threshold,
            )
            self._thread = threading.Thread(
                target=self._run, name="jarvis-wakeword", daemon=True
            )
            self._thread.start()
        self._publish({"kind": "status", **self.status()})
        return self.status()

    def stop(self, *, wait: bool = True) -> dict:
        self._stop.set()
        with self._lock:
            self.enabled = False
            self.state = "disabled"
            audio, thread = self._audio, self._thread
        if audio is not None:
            with contextlib.suppress(Exception):
                if isinstance(audio, subprocess.Popen):
                    audio.terminate()
                else:
                    audio.abort()
        if wait and thread and thread is not threading.current_thread():
            thread.join(timeout=3)
            if thread.is_alive():
                raise RuntimeError("O serviço de microfone ainda está encerrando.")
        self._publish({"kind": "status", **self.status()})
        return self.status()

    def heartbeat(self, client_id: str, busy: bool, reason: str | None = None) -> None:
        with self._lock:
            if self.owner_id == client_id:
                self._heartbeat = time.monotonic()
                self._busy = busy
                self._busy_reason = (reason or "interface_busy") if busy else None

    @contextlib.contextmanager
    def _capture(self):
        """PortAudio on supported machines, native PulseAudio on Linux otherwise."""
        try:
            import sounddevice as sd

            device: str | int | None = os.environ.get("OPENJARVIS_WAKE_DEVICE")
            if device and device.isdigit():
                device = int(device)
            stream = sd.RawInputStream(
                samplerate=16000,
                blocksize=1280,
                channels=1,
                dtype="int16",
                device=device,
            )
            stream.start()
        except (ImportError, OSError) as exc:
            diagnostic_log(
                "PortAudio indisponível (%s); tentando PulseAudio/parec", exc
            )
            if not shutil.which("parec"):
                raise RuntimeError(
                    "Instale PortAudio (libportaudio2) ou PulseAudio/parec "
                    "para acessar o microfone."
                ) from exc
            args = [
                "parec",
                "--raw",
                "--format=s16le",
                "--rate=16000",
                "--channels=1",
                "--latency-msec=80",
            ]
            source = os.environ.get("OPENJARVIS_WAKE_PULSE_SOURCE")
            if source:
                args.append(f"--device={source}")
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            with self._lock:
                self._audio = process
                self.audio_backend = "pulseaudio"
                self.audio_source = source or "padrão"
            if not source and shutil.which("pactl"):
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    self.audio_source = subprocess.run(
                        ["pactl", "get-default-source"],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=2,
                    ).stdout.strip()
            try:
                yield lambda: process.stdout.read(2560)
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                process.stdout.close()
        else:
            with self._lock:
                self._audio = stream
                self.audio_backend = "sounddevice"
                self.audio_source = str(stream.device)
            try:
                yield lambda: bytes(stream.read(1280)[0])
            finally:
                stream.close()

    def detect(self, text: str, now: float | None = None) -> bool:
        """Debounce exact-word detections; never match 'computadores'."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if not self.enabled or self._busy or now < self._inhibit_until:
                return False
            if not wake_tokens(text) or now - self._last_detection < 4:
                return False
            self._last_detection = now
            self._inhibit_until = now + 3
            self.telemetry["detections"] += 1
        diagnostic_log(
            "ATIVAÇÃO alias=%s cliente=%s texto=%r",
            sorted(wake_tokens(text)),
            self.owner_id,
            text,
        )
        self._publish(
            {"kind": "wake", "word": "computador", "id": time.time_ns()},
            owner_only=True,
        )
        return True

    def _audio_diagnostics(
        self, data: bytes, now: float, paused_reason: str | None
    ) -> None:
        rms, dbfs = audio_level(data)
        with self._lock:
            self.telemetry.update(
                rms=round(rms, 6), dbfs=round(dbfs, 1), paused_reason=paused_reason
            )
            self.telemetry["frames"] += 1
            self.telemetry["audio_bytes"] += len(data)
        if now - self._last_audio_log >= 1:
            diagnostic_log(
                "audio backend=%s bytes=%d frames=%d RMS=%.5f "
                "volume=%.2f%% dBFS=%.1f processados=%d pausa=%s",
                self.audio_backend,
                self.telemetry["audio_bytes"],
                self.telemetry["frames"],
                rms,
                rms * 100,
                dbfs,
                self.telemetry["processed_frames"],
                paused_reason or "não",
            )
            self._last_audio_log = now
        self._publish_telemetry(now)

    def _publish_telemetry(self, now: float, force: bool = False) -> None:
        if force or now - self._last_telemetry >= 0.25:
            with self._lock:
                event = {"kind": "telemetry", **self.telemetry}
            self._publish(event, owner_only=True)
            self._last_telemetry = now

    def _run(self) -> None:
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            SetLogLevel(-1)
            if self._model is None:
                self._model = Model(str(self.model_path))
            recognizers = [("pt", KaldiRecognizer(
                self._model, 16000, json.dumps(["computador", "[unk]"])
            ))]
            if self.english_path.is_dir():
                if self._english_model is None:
                    self._english_model = Model(str(self.english_path))
                recognizers.append(("en", KaldiRecognizer(
                    self._english_model, 16000, json.dumps(["computer", "[unk]"])
                )))
            for _, recognizer in recognizers:
                recognizer.SetWords(True)
                recognizer.SetPartialWords(False)
            if self._stop.is_set():
                return
            previous = {language: "" for language, _ in recognizers}
            stable = {language: 0 for language, _ in recognizers}
            paused = False
            with self._capture() as read:
                self.state = "listening"
                diagnostic_log(
                    "Microfone aberto backend=%s fonte=%s 16000Hz mono PCM16",
                    self.audio_backend,
                    self.audio_source,
                )
                self._publish({"kind": "status", **self.status()})
                while not self._stop.is_set():
                    data = read()
                    if self._stop.is_set():
                        break
                    if not data:
                        raise RuntimeError(
                            "O microfone do sistema não está fornecendo áudio."
                        )
                    now = time.monotonic()
                    if now - self._heartbeat > 15:
                        diagnostic_log("Encerrando: sem heartbeat do frontend por 15s")
                        break  # A disconnected browser cannot keep the microphone open.
                    busy = self._busy or now < self._inhibit_until
                    reason = (
                        self._busy_reason
                        if self._busy
                        else "cooldown"
                        if now < self._inhibit_until
                        else None
                    )
                    self._audio_diagnostics(data, now, reason)
                    if busy:
                        if not paused:
                            for _, recognizer in recognizers:
                                recognizer.Reset()
                        paused = True
                        previous = {language: "" for language, _ in recognizers}
                        stable = {language: 0 for language, _ in recognizers}
                        continue
                    if paused:
                        for _, recognizer in recognizers:
                            recognizer.Reset()
                        paused = False
                    self.telemetry["processed_frames"] += 1
                    for language, recognizer in recognizers:
                        final = recognizer.AcceptWaveform(data)
                        result = json.loads(
                            recognizer.Result() if final else recognizer.PartialResult()
                        )
                        text = result.get("text" if final else "partial", "")
                        stable[language] = (
                            stable[language] + 1 if text == previous[language] else 1
                        )
                        previous[language] = text
                        words = result.get("result" if final else "partial_result", [])
                        confidence = max(
                            (
                                word.get("conf", 0)
                                for word in words
                                if wake_tokens(word.get("word", ""))
                            ),
                            default=0.0,
                        )
                        stable_partial = (
                            not final
                            and not words
                            and bool(wake_tokens(text))
                            and stable[language] >= self.stable_frames
                        )
                        if text:
                            self.telemetry.update(
                                last_text=text,
                                language=language,
                                confidence=round(confidence, 3),
                                validation="partial_stable"
                                if stable_partial
                                else "final"
                                if final
                                else "partial",
                            )
                        if text and (
                            text != self._last_text_log.get(language) or final
                        ):
                            diagnostic_log(
                                "Vosk %s %s reconheceu=%r confiança_alias=%s "
                                "limiar=%.2f estável=%d",
                                language,
                                "final" if final else "parcial",
                                text,
                                f"{confidence:.3f}" if words else "n/d",
                                self.threshold,
                                stable[language],
                            )
                            self._last_text_log[language] = text
                            self._publish_telemetry(now, force=True)
                        confident = confidence >= self.threshold or stable_partial
                        if (
                            confident
                            and (final or stable[language] >= self.stable_frames)
                            and self.detect(text, now)
                        ):
                            self._publish_telemetry(now, force=True)
                            recognizer.Reset()
                            previous[language], stable[language] = "", 0
        except Exception as exc:
            if not self._stop.is_set():
                logger.exception("Wake-word listener failed")
                self.error = str(exc)
                self.state = "error"
        finally:
            with self._lock:
                self._audio = None
                self.enabled = False
                if self.state != "error":
                    self.state = "disabled"
            self._publish({"kind": "status", **self.status()})
