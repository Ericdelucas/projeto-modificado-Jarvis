"""Local XTTS voice cloning from a configured reference recording."""

from __future__ import annotations

import importlib.util
import io
import os
import threading
from pathlib import Path

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult


@TTSRegistry.register("xtts")
class XTTSTTSBackend(TTSBackend):
    backend_id = "xtts"

    def __init__(self):
        self._model = None
        self._conditioning = None
        self._lock = threading.Lock()
        self._reference = Path(os.environ.get("JARVIS_VOICE_REFERENCE", ""))
        self._model_dir = Path(os.environ.get("JARVIS_XTTS_MODEL", ""))

    def health(self):
        return (
            importlib.util.find_spec("TTS") is not None
            and self._reference.is_file()
            and all(
                (self._model_dir / f).is_file()
                for f in ("model.pth", "config.json", "vocab.json")
            )
        )

    def available_voices(self):
        return ["lucas"] if self.health() else []

    def synthesize(self, text, *, voice_id="", speed=1.0, output_format="wav"):
        if voice_id not in ("", "lucas"):
            raise ValueError("XTTS is configured with the Lucas reference only")
        if output_format != "wav":
            raise ValueError("XTTS supports WAV output")
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Voice speed must be between 0.5 and 2.0")
        import soundfile as sf
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts

        with self._lock:
            if self._model is None:
                config = XttsConfig()
                config.load_json(str(self._model_dir / "config.json"))
                model = Xtts.init_from_config(config)
                model.load_checkpoint(
                    config, checkpoint_dir=str(self._model_dir), eval=True
                )
                self._conditioning = model.get_conditioning_latents(
                    audio_path=[str(self._reference)]
                )
                self._model = model
            latent, embedding = self._conditioning
            audio = self._model.inference(
                text,
                "pt",
                latent,
                embedding,
                speed=speed,
                enable_text_splitting=True,
            )["wav"]
        buffer = io.BytesIO()
        sf.write(buffer, audio, 24000, format="WAV")
        return TTSResult(
            audio=buffer.getvalue(),
            format="wav",
            voice_id="lucas",
            sample_rate=24000,
            duration_seconds=len(audio) / 24000,
            metadata={"backend": "xtts", "language": "pt"},
        )
