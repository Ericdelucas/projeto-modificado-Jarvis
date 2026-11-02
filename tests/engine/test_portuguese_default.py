"""Portuguese defaults survive caller prompts and repeated normalization."""

from openjarvis.core.config import AgentConfig
from openjarvis.core.language import (
    DEFAULT_GREETING,
    DEFAULT_SYSTEM_PROMPT,
    portuguese_messages,
)
from openjarvis.core.types import Message, Role
from openjarvis.server.routes import _ensure_identity_prompt


def test_ollama_language_default_preserves_tools_and_is_idempotent():
    messages = [
        {"role": "system", "content": "Use tools when needed."},
        {"role": "user", "content": "Hello"},
    ]
    result = portuguese_messages(messages)
    assert DEFAULT_SYSTEM_PROMPT in result[0]["content"]
    assert "Use tools when needed." in result[0]["content"]
    assert result[1] == messages[1]
    assert portuguese_messages(result) == result
    assert AgentConfig().default_system_prompt == DEFAULT_SYSTEM_PROMPT


def test_api_applies_portuguese_with_caller_system_prompt():
    result = _ensure_identity_prompt(
        [
            Message(role=Role.SYSTEM, content="Use tools when needed."),
            Message(role=Role.USER, content="Hello"),
        ],
        None,
    )
    assert DEFAULT_SYSTEM_PROMPT in result[0].text
    assert DEFAULT_GREETING == "Olá! Como posso ajudar você hoje?"
    assert DEFAULT_GREETING in result[0].text
    assert "Use tools when needed." in result[0].text
    assert _ensure_identity_prompt(result, None)[0].text == result[0].text
