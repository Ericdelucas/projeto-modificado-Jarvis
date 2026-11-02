"""Brazilian Portuguese neural speech through Microsoft's online Edge service."""

import html
import re
import unicodedata
from collections.abc import AsyncIterator

VOICE = "pt-BR-AntonioNeural"
RATE = "-5%"
PITCH = "-2Hz"


def clean_speech_text(text: str) -> str:
    """Remove reasoning, code blocks and presentation markup from spoken prose."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"```.*?```|~~~.*?~~~", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", text)
    text = re.sub(r"[*_`~#|]", "", text)
    # Remove emoji, variation selectors, joiners and decorative symbols.
    text = "".join(
        char
        for char in text
        if unicodedata.category(char) not in {"So", "Sk", "Sm", "Cf", "Cs"}
        and char not in {"\ufe0f", "\ufe0e", "\u20e3"}
    )
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[=+^{}\[\]\\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # A breath only at a clause boundary in a long span, never per word.
    words = text.split()
    span = 0
    for index, word in enumerate(words):
        span += 1
        if span >= 22 and word.lower() in {"mas", "porque", "então", "porém", "embora"}:
            words[index - 1] = words[index - 1].rstrip(",;:") + ","
            span = 0
        elif span >= 45 and index > 0:
            words[index - 1] = words[index - 1].rstrip(",;:") + ","
            span = 1
        if re.search(r"[.!?;:,]$", word):
            span = 0
    return " ".join(words)


async def stream_mp3(text: str) -> AsyncIterator[bytes]:
    """Forward audio as it arrives, preserving the provider's MP3 encoding."""
    import edge_tts

    speech = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH, volume="+0%")
    received = False
    async for chunk in speech.stream():
        if chunk["type"] == "audio":
            received = True
            yield chunk["data"]
    if not received:
        raise RuntimeError("Edge TTS returned no audio")


async def synthesize_mp3(text: str) -> bytes:
    """Compatibility path for downloads and manual reading."""
    return b"".join([chunk async for chunk in stream_mp3(text)])
