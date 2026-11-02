import json
from unittest.mock import MagicMock

import pytest

from openjarvis.operators.navigation_intent import resolve_navigation


def engine_response(action="search", app="Firefox", query="Felipe Neto"):
    engine = MagicMock()
    engine.generate.return_value = {
        "content": json.dumps(
            {
                "action": action,
                "app": app,
                "query": query,
            }
        )
    }
    return engine


@pytest.mark.parametrize(
    "phrase",
    [
        "Joga no Firefox uma busca por Felipe Neto",
        "Tô querendo ver na internet algo sobre Felipe Neto, usa o Firefox",
        "Me acha uns resultados de Felipe Neto com o Firefox",
    ],
)
def test_unseen_phrasing_uses_semantics_and_executes_nothing(phrase):
    engine = engine_response()
    assert resolve_navigation(phrase, [], engine, "qwen3:1.7b") == {
        "action": "browser_search",
        "app": "Firefox",
        "text": "Felipe Neto",
    }
    assert engine.generate.call_args.kwargs["model"] == "qwen3:1.7b"
    assert "tools" not in engine.generate.call_args.kwargs


def test_context_resolves_reference_from_prior_user_message():
    engine = engine_response()
    assert (
        resolve_navigation(
            "Vai atrás daquele assunto na internet",
            ["Felipe Neto no Firefox"],
            engine,
            "general",
        )["text"]
        == "Felipe Neto"
    )


def test_normal_conversation_is_not_turned_into_navigation():
    engine = engine_response(action="none", app="navegador", query="")
    assert (
        resolve_navigation("Explique o que é uma classe", [], engine, "general") is None
    )


def test_rewritten_query_uses_user_text_instead_of_blocking_search():
    engine = engine_response(query="biografia oficial de Felipe Neto")
    result = resolve_navigation("Me ache Felipe Neto na web", [], engine, "general")
    assert result["text"] == "Me ache Felipe Neto na web"


def test_capitalization_and_spacing_do_not_reject_a_new_term():
    engine = engine_response(query="BURACOS   NEGROS")
    result = resolve_navigation(
        "Busque buracos negros no Firefox", [], engine, "general"
    )
    assert result["text"] == "buracos negros"


@pytest.mark.parametrize(
    "topic",
    [
        "nebulosas ZQX-781",
        "cerâmica raku",
        "Açaí & café: 2027?",
        "paleobotânica",
        "xenobiologia",
        "história de uma cidade desconhecida",
    ],
)
def test_new_topics_have_no_allowlist_or_script_requirement(topic):
    engine = engine_response(query=topic)
    result = resolve_navigation(
        f"Traz resultados da internet de {topic}", [], engine, "general"
    )
    assert result["text"] == topic
    engine.generate.assert_called_once()


def test_even_a_previously_scripted_search_is_interpreted_semantically():
    engine = engine_response(query="um assunto totalmente novo")
    resolve_navigation("pesquise um assunto totalmente novo", [], engine, "general")
    engine.generate.assert_called_once()


def test_missing_extracted_query_does_not_block_the_user_request():
    engine = engine_response(query="")
    result = resolve_navigation(
        "Me acha na internet algo de fotogrametria", [], engine, "general"
    )
    assert result["text"] == "Me acha na internet algo de fotogrametria"


def test_model_can_resolve_app_launch_without_fixed_command_prefix():
    engine = engine_response(action="open_app", app="Android Studio", query="")
    assert resolve_navigation(
        "Tô precisando usar o Android Studio", [], engine, "general"
    ) == {
        "action": "open_app",
        "app": "Android Studio",
    }


def test_malformed_decision_does_not_become_a_success_confirmation():
    engine = engine_response()
    engine.generate.return_value = {"content": "Pesquisa realizada!"}
    with pytest.raises(ValueError, match="interpretar"):
        resolve_navigation("Joga isso na internet", [], engine, "general")


def test_compound_browser_request_cannot_be_reduced_to_opening():
    task = "Abra o Firefox e pesquise FECAP e depois abra o site oficial"
    result = resolve_navigation(task, [], engine_response(action="open_app"), "general")
    assert result == {"action": "browser_task", "task": task}
