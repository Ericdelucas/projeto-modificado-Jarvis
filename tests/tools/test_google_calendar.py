"""Live Calendar dates, OAuth persistence and agent tool results (no Google calls)."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response

from openjarvis.connectors.gcalendar_live import (
    SCOPES,
    CalendarAuthRequired,
    CalendarUnavailable,
    GoogleCalendarClient,
)
from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.google_calendar import GoogleCalendarTodayTool


def client(tmp_path, zone="America/Araguaina"):
    return GoogleCalendarClient(
        SimpleNamespace(timezone=zone, client_secrets=""),
        token_path=tmp_path / "private" / "token.json",
    )


def test_today_primary_full_local_day_pagination_and_all_day(tmp_path):
    calendar = client(tmp_path)
    service = MagicMock()
    service.events.return_value.list.return_value.execute.side_effect = [
        {
            "items": [
                {
                    "id": "1",
                    "summary": "Reunião",
                    "start": {"dateTime": "2026-11-01T12:30:00Z"},
                    "end": {"dateTime": "2026-11-01T13:00:00Z"},
                }
            ],
            "nextPageToken": "page2",
        },
        {
            "items": [
                {
                    "id": "2",
                    "summary": "Feriado",
                    "start": {"date": "2026-11-01"},
                    "end": {"date": "2026-11-02"},
                }
            ]
        },
    ]
    with patch.object(calendar, "_service", return_value=service):
        result = calendar.today(now=datetime(2026, 11, 2, 1, tzinfo=timezone.utc))
    assert result["date"] == "2026-11-01"  # UTC is already tomorrow.
    first, second = service.events.return_value.list.call_args_list
    assert first.kwargs["calendarId"] == "primary"
    assert first.kwargs["timeMin"] == "2026-11-01T00:00:00-03:00"
    assert first.kwargs["timeMax"] == "2026-11-02T00:00:00-03:00"
    assert first.kwargs["timeZone"] == "America/Araguaina"
    assert first.kwargs["singleEvents"] is True
    assert first.kwargs["orderBy"] == "startTime"
    assert second.kwargs["pageToken"] == "page2"
    assert result["events"][0]["start"] == "2026-11-01T09:30:00-03:00"
    assert result["events"][1]["all_day"] is True
    service.close.assert_called_once()


def test_dst_day_uses_local_midnights_not_fixed_24_hours(tmp_path):
    calendar = client(tmp_path, "America/New_York")
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": []}
    with patch.object(calendar, "_service", return_value=service):
        calendar.today(now=datetime(2026, 3, 8, 12, tzinfo=timezone.utc))
    args = service.events.return_value.list.call_args.kwargs
    assert args["timeMin"].endswith("-05:00")
    assert args["timeMax"].endswith("-04:00")
    seconds = (
        datetime.fromisoformat(args["timeMax"])
        - datetime.fromisoformat(args["timeMin"])
    ).total_seconds()
    assert seconds == 23 * 3600


def test_empty_calendar_is_not_an_api_failure(tmp_path):
    calendar = client(tmp_path)
    service = MagicMock()
    request = service.events.return_value.list.return_value
    request.execute.return_value = {"items": []}
    with patch.object(calendar, "_service", return_value=service):
        result = calendar.today()
        assert result["status"] == "empty"
        assert (
            result["message"] == "Você não tem nenhum compromisso agendado para hoje."
        )
        request.execute.side_effect = HttpError(Response({"status": "403"}), b"quota")
        with pytest.raises(CalendarUnavailable):
            calendar.today()


def test_oauth_is_explicit_read_only_pkce_loopback_and_persists_owner_only(tmp_path):
    calendar = client(tmp_path)
    secrets = tmp_path / "client.json"
    secrets.write_text(json.dumps({"installed": {"client_id": "test"}}))
    credentials = MagicMock(valid=True, refresh_token="fake")
    credentials.has_scopes.return_value = True
    credentials.to_json.return_value = '{"refresh_token":"fake"}'
    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file"
    ) as factory:
        factory.return_value.run_local_server.return_value = credentials
        calendar.connect(secrets)
    assert factory.call_args.kwargs["autogenerate_code_verifier"] is True
    assert factory.call_args.args[1] == SCOPES
    args = factory.return_value.run_local_server.call_args.kwargs
    assert args["host"] == "127.0.0.1" and args["port"] == 0
    assert args["access_type"] == "offline"
    assert "readonly" in SCOPES[0]
    assert calendar.token_path.stat().st_mode & 0o777 == 0o600
    assert calendar.token_path.parent.stat().st_mode & 0o777 == 0o700


def test_saved_token_is_reused_and_expired_token_refreshed(tmp_path):
    calendar = client(tmp_path)
    calendar.token_path.parent.mkdir()
    calendar.token_path.write_text("{}")
    credentials = MagicMock(valid=True, refresh_token="fake")
    credentials.has_scopes.return_value = True
    credentials.to_json.return_value = '{"token":"updated"}'
    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        return_value=credentials,
    ):
        assert calendar.credentials() is credentials
        credentials.refresh.assert_not_called()
        credentials.valid = False
        assert calendar.credentials() is credentials
        credentials.refresh.assert_called_once()
        assert json.loads(calendar.token_path.read_text())["token"] == "updated"
        credentials.refresh.side_effect = RefreshError("private-secret")
        with pytest.raises(CalendarAuthRequired) as caught:
            calendar.credentials()
        assert "private-secret" not in str(caught.value)


def test_tool_registered_and_auth_failure_never_becomes_empty(tmp_path):
    import importlib

    import openjarvis.tools.google_calendar as module

    importlib.reload(module)
    assert ToolRegistry.get("google_calendar_today") is module.GoogleCalendarTodayTool
    tool = GoogleCalendarTodayTool(client=client(tmp_path))
    result = tool.execute()
    assert result.success is False
    payload = json.loads(result.content)
    assert payload["status"] == "auth_required"
    assert "calendar connect" in payload["message"]
    assert "events" not in payload


@pytest.mark.parametrize(
    "events, answer",
    [
        ([], "Você não tem nenhum compromisso agendado para hoje."),
        (
            [{"title": "Reunião", "start": "2026-11-01T09:30:00-03:00"}],
            "Hoje você tem uma reunião às 9h30.",
        ),
    ],
)
def test_agent_calls_calendar_and_receives_data_before_answering(events, answer):
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.core.types import Role

    fake_client = MagicMock()
    fake_client.today.return_value = {
        "status": "ok" if events else "empty",
        "events": events,
    }
    engine = MagicMock()
    engine.engine_id = "test"
    engine.generate.side_effect = [
        {
            "content": "",
            "tool_calls": [
                {"id": "calendar-1", "name": "google_calendar_today", "arguments": "{}"}
            ],
        },
        {"content": answer},
    ]
    agent = OrchestratorAgent(
        engine, "qwen3:1.7b", tools=[GoogleCalendarTodayTool(fake_client)], max_turns=3
    )
    result = agent.run("O que eu tenho para hoje?")
    fake_client.today.assert_called_once()
    assert result.content == answer
    received = engine.generate.call_args.args[0]
    assert any(
        message.role == Role.TOOL and '"events"' in message.text for message in received
    )


def test_google_calendar_configuration_loads_and_server_allows_tool(tmp_path):
    from openjarvis.cli.serve import _resolve_allowed_tools
    from openjarvis.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        '[google_calendar]\ntimezone="America/Araguaina"\n[agent]\ntools="google_calendar_today"\n'
    )
    config = load_config(path)
    assert config.google_calendar.timezone == "America/Araguaina"
    assert _resolve_allowed_tools(config)[0] == {"google_calendar_today"}


def test_cli_calendar_commands_do_not_print_tokens(tmp_path):
    from click.testing import CliRunner

    from openjarvis.cli.calendar_cmd import calendar

    with patch("openjarvis.cli.calendar_cmd.GoogleCalendarClient") as factory:
        factory.return_value.status.return_value = {
            "configured": False,
            "timezone": "America/Araguaina",
        }
        result = CliRunner().invoke(calendar, ["status"])
        assert result.exit_code == 0
        assert json.loads(result.output)["configured"] is False
        factory.return_value.today.side_effect = CalendarAuthRequired(
            "Execute jarvis calendar connect."
        )
        result = CliRunner().invoke(calendar, ["today"])
        assert result.exit_code == 1
        assert "calendar connect" in result.output


def test_official_oauth_url_includes_state_and_pkce_without_network():
    from urllib.parse import parse_qs, urlparse

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        SCOPES,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = "http://127.0.0.1:12345/"
    url, state = flow.authorization_url(access_type="offline")
    query = parse_qs(urlparse(url).query)
    assert query["state"] == [state]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    assert query["scope"] == SCOPES
