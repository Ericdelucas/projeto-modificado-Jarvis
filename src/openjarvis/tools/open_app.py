"""Discover and launch installed desktop applications, without a fixed catalogue."""

from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def normalize_app(value: str) -> str:
    value = "".join(
        c
        for c in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(c)
    )
    value = re.sub(r"[^\w]+|_", " ", value).strip()
    value = re.sub(r"^(?:por favor |please )", "", value)
    value = re.sub(
        r"^(?:abra|abrir|abre|inicie|iniciar|execute|executar|open|launch|start)\s+",
        "",
        value,
    )
    value = re.sub(r"^(?:o|a|os|as|um|uma|the)\s+", "", value)
    return re.sub(r"\s+(?:por favor|please)$", "", value).strip()


def launch_environment() -> dict[str, str]:
    """Keep the desktop session, without the editor's Snap GTK libraries."""
    env = os.environ.copy()
    if env.get("SNAP_NAME") != "code" and env.get("SNAP_INSTANCE_NAME") != "code":
        return env
    original = env.get("XDG_DATA_DIRS_VSCODE_SNAP_ORIG")
    if original:
        env["XDG_DATA_DIRS"] = original
    else:
        env["XDG_DATA_DIRS"] = (
            ":".join(
                part
                for part in env.get("XDG_DATA_DIRS", "").split(":")
                if part and "/snap/code/" not in part
            )
            or "/usr/local/share:/usr/share"
        )
    for key in list(env):
        if key.startswith("SNAP") or key.endswith("_VSCODE_SNAP_ORIG"):
            env.pop(key, None)
    for key in (
        "GSETTINGS_SCHEMA_DIR",
        "GTK_PATH",
        "GTK_EXE_PREFIX",
        "GTK_DATA_PREFIX",
        "GIO_MODULE_DIR",
        "GIO_EXTRA_MODULES",
        "GDK_PIXBUF_MODULE_FILE",
        "GDK_PIXBUF_MODULEDIR",
        "GTK_IM_MODULE_FILE",
    ):
        env.pop(key, None)
    return env


def application_directories() -> list[Path]:
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    paths = [data_home / "applications"]
    paths.extend(Path(part) / "applications" for part in data_dirs.split(":") if part)
    paths.extend(
        [
            home / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"),
            Path("/var/lib/snapd/desktop/applications"),
        ]
    )
    return list(dict.fromkeys(path.expanduser() for path in paths))


@dataclass(frozen=True)
class DesktopApp:
    path: Path
    names: tuple[str, ...]
    search_names: tuple[str, ...]
    exec_line: str
    icon: str = ""
    cwd: str = ""
    terminal: bool = False
    no_display: bool = False
    categories: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.names[0]


def desktop_apps(directories: Sequence[Path]) -> list[DesktopApp]:
    # Reuse parsed entries while still noticing installs, removals and edits
    # on every request. Include PATH because TryExec depends on it.
    fingerprint = []
    for directory in directories:
        for path in sorted(directory.rglob("*.desktop")):
            try:
                info = path.stat()
                fingerprint.append(
                    (str(path), info.st_mtime_ns, info.st_ctime_ns, info.st_size)
                )
            except OSError:
                continue
    return list(
        _cached_desktop_apps(
            tuple(directories), tuple(fingerprint), os.environ.get("PATH", "")
        )
    )


@lru_cache(maxsize=8)
def _cached_desktop_apps(
    directories: tuple[Path, ...], fingerprint: tuple, executable_path: str
) -> tuple[DesktopApp, ...]:
    apps = []
    seen = set()
    for directory in directories:
        for path in sorted(directory.rglob("*.desktop")):
            desktop_id = str(path.relative_to(directory)).replace(os.sep, "-")
            if desktop_id in seen:
                continue
            seen.add(desktop_id)  # User Hidden=true entries mask system entries.
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.optionxform = str
            try:
                parser.read_string(path.read_text(encoding="utf-8"))
                section = parser["Desktop Entry"]
                if (
                    section.get("Type", "Application") != "Application"
                    or section.get("Hidden", "").lower() == "true"
                ):
                    continue
                names = tuple(
                    dict.fromkeys(
                        value
                        for key, value in section.items()
                        if key == "Name" or key.startswith("Name[")
                    )
                )
                if not names:
                    continue
                executable = section.get("TryExec")
                if executable and not shutil.which(executable):
                    continue
                line = section.get("Exec", "")
                if not line and section.get("DBusActivatable", "").lower() != "true":
                    continue
                generic = [
                    value
                    for key, value in section.items()
                    if key == "GenericName" or key.startswith("GenericName[")
                ]
                keywords = [
                    item
                    for key, value in section.items()
                    if key == "Keywords" or key.startswith("Keywords[")
                    for item in value.split(";")
                    if item
                ]
                apps.append(
                    DesktopApp(
                        path=path.resolve(),
                        names=names,
                        search_names=tuple(
                            [
                                path.stem,
                                path.name,
                                str(path.resolve()),
                                *generic,
                                *keywords,
                            ]
                        ),
                        exec_line=line,
                        icon=section.get("Icon", ""),
                        cwd=section.get("Path", ""),
                        terminal=section.get("Terminal", "").lower() == "true",
                        no_display=section.get("NoDisplay", "").lower() == "true",
                        categories=tuple(section.get("Categories", "").split(";")),
                    )
                )
            except (OSError, UnicodeError, configparser.Error, KeyError):
                continue  # One malformed third-party entry must not break discovery.
    return tuple(apps)


def match_score(query: str, app: DesktopApp) -> int:
    compact = query.replace(" ", "")
    best = 0
    for label in (*app.names, *app.search_names):
        normalized = normalize_app(label)
        words = normalized.split()
        abbreviation = "".join(word[0] for word in words[:-1]) + (
            words[-1] if words else ""
        )
        if query == normalized or compact == normalized.replace(" ", ""):
            score = 100 if label in app.names else 90
        elif compact == abbreviation:
            score = 85
        elif query and set(query.split()).issubset(words):
            score = 75
        else:
            score = 0
        best = max(best, score)
    return best - int(app.no_display) if best else 0


def exec_arguments(app: DesktopApp) -> list[str]:
    """Expand a desktop Exec without shell or file/URL arguments."""
    line = re.sub(
        r"\\([sntr\\])",
        lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}[m[1]],
        app.exec_line,
    )
    args = []
    for word in shlex.split(line):
        if word in ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%v", "%m"):
            continue
        if word == "%i":
            if app.icon:
                args.extend(["--icon", app.icon])
            continue

        def expand(match):
            code = match[1]
            if code == "%":
                return "%"
            if code == "c":
                return app.name
            if code == "k":
                return str(app.path)
            if code in "fFuUdDnNvm":
                return ""
            raise ValueError("Código de campo inválido no arquivo .desktop.")

        args.append(re.sub(r"%(.)", expand, word))
    if not args:
        raise ValueError("O aplicativo não possui comando Exec utilizável sem GIO.")
    if app.terminal:
        terminal = shutil.which("x-terminal-emulator")
        if not terminal:
            raise ValueError("Nenhum emulador de terminal padrão foi encontrado.")
        args = [terminal, "-e", *args]
    return args


@ToolRegistry.register("open_app")
class OpenAppTool(BaseTool):
    tool_id = "open_app"

    def __init__(self, *, directories: Sequence[Path] | None = None):
        self.directories = directories

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Abre qualquer aplicativo instalado no Ubuntu em segundo plano. "
                "Pesquisa arquivos .desktop pelo nome amigável, incluindo nomes "
                "traduzidos, e usa o comando real da instalação. Se necessário, "
                "procura o executável no PATH. Informe somente o nome em app "
                "(por exemplo Android Studio, Firefox ou Visual Studio Code)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "description": "Nome ou caminho do aplicativo.",
                    }
                },
                "required": ["app"],
                "additionalProperties": False,
            },
            category="system",
            required_capabilities=["code:execute"],
            timeout_seconds=15,
        )

    def execute(self, **params: Any) -> ToolResult:
        value = params.get("app")
        url = params.get("url")
        if url is not None:
            from urllib.parse import urlsplit

            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                valid = (
                    parsed is not None
                    and len(url) <= 8000
                    and not any(ord(char) < 32 for char in url)
                    and parsed.scheme in {"https", "http"}
                    and bool(parsed.netloc)
                )
            except ValueError:
                valid = False
            if not valid:
                return self._result(False, "Informe uma URL HTTP(S) válida.")
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            return self._result(False, "Informe o nome do aplicativo em app.")
        query = normalize_app(value)
        directories = (
            self.directories
            if self.directories is not None
            else application_directories()
        )
        apps = desktop_apps(directories)
        # Read the desktop default browser instead of naming a particular app.
        if query in {"navegador", "browser", "internet"} and shutil.which(
            "xdg-settings"
        ):
            try:
                default = subprocess.run(
                    ["xdg-settings", "get", "default-web-browser"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=True,
                ).stdout.strip()
                selected = [app for app in apps if app.path.name == default]
            except (OSError, subprocess.SubprocessError):
                selected = []
        else:
            selected = []
        if not selected:
            ranked = [(match_score(query, app), app) for app in apps]
            best = max((score for score, _ in ranked), default=0)
            selected = [app for score, app in ranked if score == best and score > 0]
        try:
            if len(selected) > 1:
                return self._result(
                    False,
                    "Encontrei mais de um aplicativo. Informe o nome completo.",
                    candidates=[
                        {
                            "name": app.name,
                            "desktop_file": app.path.name,
                            "path": str(app.path),
                        }
                        for app in selected
                    ],
                )
            if selected:
                app = selected[0]
                gio = shutil.which("gio")
                # Launch Exec directly so a successful GIO wrapper cannot hide
                # an immediate crash in the actual application.
                args = (
                    exec_arguments(app)
                    if app.exec_line
                    else (
                        [gio, "launch", str(app.path)] if gio else exec_arguments(app)
                    )
                )
                cwd = app.cwd or str(Path.home())
                name = app.name
                if url is not None:
                    if not gio:
                        return self._result(
                            False,
                            "GIO é necessário para abrir URLs neste aplicativo.",
                        )
                    # GIO applies desktop field codes correctly, including Snap
                    # and Flatpak wrappers; never concatenate a shell command.
                    args = [gio, "launch", str(app.path), url]
            else:
                # Resolve a single executable; its path may contain spaces.
                executable = shutil.which(value.strip())
                if executable is None:
                    executable = shutil.which(query.replace(" ", "-"))
                if executable is None and query in {"terminal", "console", "consola"}:
                    executable = shutil.which("x-terminal-emulator")
                if executable is None:
                    return self._result(
                        False,
                        "Aplicativo não encontrado nas entradas .desktop nem no PATH.",
                    )
                args, cwd, name = [executable], str(Path.home()), value.strip()
                if url is not None:
                    args.append(url)
            with tempfile.TemporaryFile(mode="w+t") as errors:
                process = subprocess.Popen(
                    args,
                    shell=False,
                    start_new_session=True,
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=errors,
                    cwd=cwd,
                    env=launch_environment(),
                )
                try:
                    process.wait(timeout=0.75)
                except subprocess.TimeoutExpired:
                    pass  # A running GUI must not block the API.
                exit_code = process.poll()
                if exit_code not in (None, 0):
                    errors.seek(0)
                    detail = errors.read(2000).strip()
                    return self._result(
                        False,
                        f"Não foi possível iniciar {name} (código {exit_code})."
                        + (f" {detail}" if detail else ""),
                    )
            return self._result(
                True, f"Abertura de {name} solicitada.", app=name, pid=process.pid
            )
        except (OSError, ValueError) as error:
            return self._result(
                False, f"Não foi possível iniciar o aplicativo: {error}"
            )

    def _result(self, success: bool, message: str, **data: Any) -> ToolResult:
        return ToolResult(
            self.tool_id,
            json.dumps({"message": message, **data}, ensure_ascii=False),
            success=success,
        )
