"""Live, read-only Google Calendar tool available to local tool-calling agents."""

import json

from openjarvis.connectors.gcalendar_live import (
    CalendarAuthRequired,
    CalendarUnavailable,
    GoogleCalendarClient,
)
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("google_calendar_today")
class GoogleCalendarTodayTool(BaseTool):
    tool_id = "google_calendar_today"
    is_local = False

    def __init__(self, client=None):
        self.client = client

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Consulta em tempo real os compromissos de HOJE no calendário "
                "principal do Google Calendar, no fuso local. Use para perguntas "
                "como 'O que tenho para hoje?', 'Qual minha agenda?' ou "
                "'Quais são meus compromissos?'. Retorna horários, títulos e "
                "eventos de dia inteiro. Somente leitura; não altera eventos. "
                "Não invente compromissos e não confunda falta de autorização "
                "com agenda vazia."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            category="calendar",
            timeout_seconds=60,
        )

    def execute(self, **params):
        try:
            if self.client is None:
                self.client = GoogleCalendarClient()
            result = self.client.today()
            return ToolResult(self.tool_id, json.dumps(result, ensure_ascii=False))
        except CalendarAuthRequired as exc:
            result = {"status": "auth_required", "message": str(exc)}
        except CalendarUnavailable as exc:
            result = {"status": "unavailable", "message": str(exc)}
        return ToolResult(
            self.tool_id, json.dumps(result, ensure_ascii=False), success=False
        )
