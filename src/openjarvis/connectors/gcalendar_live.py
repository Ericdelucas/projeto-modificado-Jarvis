"""Read-only, live primary-calendar queries using Google's official client."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_write_text

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]
_credentials_lock = threading.RLock()


class CalendarAuthRequired(RuntimeError):
    """An explicit local OAuth login is required, never a browser opened by the LLM."""


class CalendarUnavailable(RuntimeError):
    """Calendar could not be read; this is different from an empty calendar."""


class GoogleCalendarClient:
    def __init__(self, config=None, *, token_path: Path | None = None):
        if config is None:
            from openjarvis.core.config import load_config

            config = load_config().google_calendar
        self.config = config
        self.token_path = (
            token_path
            or get_config_dir() / "credentials" / "google-calendar-token.json"
        )

    @property
    def timezone_name(self) -> str:
        from tzlocal import get_localzone_name

        name = self.config.timezone or os.environ.get("TZ") or get_localzone_name()
        ZoneInfo(name)  # Validate the IANA timezone rather than silently using UTC.
        return name

    def _save(self, credentials) -> None:
        if self.token_path.is_symlink() or self.token_path.parent.is_symlink():
            raise CalendarAuthRequired(
                "O caminho do token não pode ser um link simbólico."
            )
        secure_write_text(self.token_path, credentials.to_json())

    def credentials(self):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        with _credentials_lock:
            if not self.token_path.is_file():
                raise CalendarAuthRequired(
                    "Conecte o Google Calendar com: jarvis calendar connect "
                    "--client-secrets /caminho/credentials.json"
                )
            if self.token_path.is_symlink() or self.token_path.parent.is_symlink():
                raise CalendarAuthRequired(
                    "O caminho do token não pode ser um link simbólico."
                )
            try:
                credentials = Credentials.from_authorized_user_file(
                    str(self.token_path), SCOPES
                )
                os.chmod(self.token_path, 0o600)
                if not credentials.valid:
                    if not credentials.refresh_token:
                        raise CalendarAuthRequired(
                            "Autorize novamente com jarvis calendar connect."
                        )
                    # Refresh requests are bounded even when Google is unreachable.
                    transport = Request()

                    def bounded_request(*args, **kwargs):
                        kwargs.setdefault("timeout", 15)
                        return transport(*args, **kwargs)

                    credentials.refresh(bounded_request)
                    self._save(credentials)
                if not credentials.has_scopes(SCOPES):
                    raise CalendarAuthRequired(
                        "A permissão de leitura não foi concedida. "
                        "Execute jarvis calendar connect."
                    )
                return credentials
            except RefreshError as exc:
                raise CalendarAuthRequired(
                    "A autorização do Google expirou ou foi revogada. "
                    "Execute jarvis calendar connect."
                ) from exc
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                raise CalendarAuthRequired(
                    "O token local é inválido. Execute jarvis calendar connect."
                ) from exc

    def connect(
        self, client_secrets: Path | None = None, *, timeout_seconds: int = 600
    ) -> None:
        from google_auth_oauthlib.flow import InstalledAppFlow

        configured = (
            os.environ.get("OPENJARVIS_GOOGLE_CLIENT_SECRETS")
            or self.config.client_secrets
        )
        path = client_secrets or (
            Path(configured).expanduser()
            if configured
            else get_config_dir() / "credentials" / "google-calendar-client.json"
        )
        if not path.is_file():
            raise CalendarAuthRequired(
                "Baixe um cliente OAuth do tipo Desktop no Google Cloud e informe "
                "--client-secrets /caminho/credentials.json."
            )
        if "installed" not in json.loads(path.read_text()):
            raise CalendarAuthRequired(
                "Use credenciais OAuth do tipo aplicativo Desktop (campo installed)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(path), SCOPES, autogenerate_code_verifier=True
        )
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            timeout_seconds=timeout_seconds,
            access_type="offline",
            prompt="consent",
            authorization_prompt_message=("Autorize a leitura no navegador: {url}"),
            success_message="Calendar conectado ao Jarvis. Pode fechar esta janela.",
        )
        if (
            not credentials
            or not credentials.valid
            or not credentials.refresh_token
            or not credentials.has_scopes(SCOPES)
        ):
            raise CalendarAuthRequired("A autorização de leitura não foi concluída.")
        with _credentials_lock:
            self._save(credentials)

    def status(self) -> dict:
        return {
            "configured": self.token_path.is_file(),
            "timezone": self.timezone_name,
            "calendar": "primary",
            "read_only": True,
        }

    def _service(self):
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build

        http = AuthorizedHttp(self.credentials(), http=httplib2.Http(timeout=15))
        return build("calendar", "v3", http=http, cache_discovery=False)

    def today(self, *, now: datetime | None = None) -> dict:
        from googleapiclient.errors import HttpError

        tz_name = self.timezone_name
        tz = ZoneInfo(tz_name)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("A data de consulta precisa incluir fuso horário.")
        day = current.astimezone(tz).date()
        start = datetime.combine(day, time.min, tzinfo=tz)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
        service = None
        try:
            service = self._service()
            events = []
            page_token = None
            seen = set()
            while True:
                result = (
                    service.events()
                    .list(
                        calendarId="primary",
                        timeMin=start.isoformat(),
                        timeMax=end.isoformat(),
                        timeZone=tz_name,
                        singleEvents=True,
                        orderBy="startTime",
                        showDeleted=False,
                        maxResults=2500,
                        pageToken=page_token,
                    )
                    .execute()
                )
                for event in result.get("items", []):
                    if event.get("status") != "cancelled":
                        events.append(self._event(event, tz))
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
                if page_token in seen:
                    raise CalendarUnavailable(
                        "A paginação do Google Calendar não foi concluída."
                    )
                seen.add(page_token)
            return {
                "status": "ok" if events else "empty",
                "date": day.isoformat(),
                "timezone": tz_name,
                "calendar": "primary",
                "events": events,
                "message": f"Você tem {len(events)} compromisso(s) para hoje."
                if events
                else "Você não tem nenhum compromisso agendado para hoje.",
            }
        except CalendarAuthRequired:
            raise
        except HttpError as exc:
            raise CalendarUnavailable(
                "Não foi possível consultar o Google Calendar "
                f"(HTTP {exc.resp.status}). "
                "Verifique a API e a permissão de leitura."
            ) from exc
        except CalendarUnavailable:
            raise
        except Exception as exc:
            raise CalendarUnavailable(
                "Não foi possível acessar o Google Calendar agora. "
                "Verifique a conexão e tente novamente."
            ) from exc
        finally:
            if service is not None:
                service.close()

    @staticmethod
    def _event(event: dict, tz: ZoneInfo) -> dict:
        def local(field):
            if "dateTime" not in field:
                return field.get("date", "")
            value = datetime.fromisoformat(field["dateTime"].replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo(field.get("timeZone", str(tz))))
            return value.astimezone(tz).isoformat()

        return {
            "id": event.get("id", ""),
            "title": event.get("summary") or "Compromisso sem título",
            "start": local(event.get("start", {})),
            "end": local(event.get("end", {})),
            "all_day": "date" in event.get("start", {}),
            "location": event.get("location", ""),
        }
