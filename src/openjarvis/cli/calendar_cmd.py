"""Explicit OAuth setup and live read-only Calendar queries."""

import json
from pathlib import Path

import click

from openjarvis.connectors.gcalendar_live import (
    CalendarAuthRequired,
    CalendarUnavailable,
    GoogleCalendarClient,
)


@click.group("calendar")
def calendar():
    """Conecte o Google Calendar e consulte sua agenda local."""


@calendar.command()
@click.option(
    "--client-secrets", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
def connect(client_secrets):
    """Abra o OAuth Google no navegador e salve o token localmente."""
    try:
        GoogleCalendarClient().connect(client_secrets)
    except Exception as exc:
        if isinstance(exc, CalendarAuthRequired):
            raise click.ClickException(str(exc)) from exc
        raise click.ClickException(
            f"O login Google não foi concluído ({type(exc).__name__}). "
            "Confira o cliente OAuth e tente novamente."
        ) from exc
    click.echo("Google Calendar conectado com acesso somente de leitura.")


@calendar.command()
def status():
    """Mostre a configuração sem exibir tokens ou dados privados."""
    click.echo(
        json.dumps(GoogleCalendarClient().status(), ensure_ascii=False, indent=2)
    )


@calendar.command()
def today():
    """Consulte os compromissos do dia no fuso configurado."""
    try:
        result = GoogleCalendarClient().today()
    except (CalendarAuthRequired, CalendarUnavailable) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
