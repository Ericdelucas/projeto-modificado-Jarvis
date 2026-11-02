"""Bounded desktop actions with a latched emergency stop and X11 focus checks."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def browser_search_intent(text: str, history: list[str] | None = None) -> dict | None:
    """Parse navigation syntax only; query text is never classified or rewritten."""
    normalized = text.casefold().strip().rstrip(".!?")
    if normalized in {
        "pare a automação",
        "parar automação",
        "pare a automacao",
        "parar automacao",
        "stop automation",
    }:
        return {"action": "stop"}
    if normalized in {"reativar automação", "reativar automacao", "resume automation"}:
        return {"action": "resume"}

    previous = None
    for message in reversed((history or [])[-20:]):
        candidate = browser_search_intent(message)
        if (
            candidate
            and candidate.get("action") == "browser_search"
            and candidate.get("text")
        ):
            previous = candidate
            break
    default_app = previous["app"] if previous else "navegador"
    if re.fullmatch(
        r"(?:faça|faca|faz|realize|execute)\s+(?:a|essa|esta)\s+"
        r"(?:pesquisa|busca)(?:\s+(?:a[ií]|agora|por favor))*",
        normalized,
    ) or normalized in {"pesquise isso", "busque isso", "pesquise novamente"}:
        return (
            dict(previous)
            if previous
            else {
                "action": "browser_search",
                "app": default_app,
                "text": "",
            }
        )

    command = re.sub(
        r"^\s*(?:(?:por favor[, ]+)|(?:quero que (?:você|voce)\s+)|"
        r"(?:(?:você|voce) pode\s+)|(?:pode\s+))*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    patterns = [
        r"(?:abra|abre|abrir|open)\s+(?:(?:o|a|the)\s+)?"
        r"(?P<app>.+?)\s+e\s+(?:pesquise|pesquisa|busque|procure)\s+"
        r"(?:sobre\s+)?(?P<query>.+)",
        r"(?:pesquise|pesquisar|pesquisa|busque|buscar|procure|procurar)\s+"
        r"(?:no|na|pelo|pela)\s+(?P<app>.+?)\s+(?:sobre|por)\s+(?P<query>.+)",
        r"(?:pesquise|pesquisar|pesquisa|busque|buscar|procure|procurar)\s+"
        r"(?:no|na)\s+(?P<app>\S+)\s+(?P<query>.+)",
        r"(?:pesquise|pesquisar|pesquisa|busque|buscar|procure|procurar)\s+"
        r"(?:sobre\s+)?(?P<query>.+)",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, command.strip(), re.IGNORECASE | re.DOTALL)
        if match:
            return {
                "action": "browser_search",
                "app": (match.groupdict().get("app") or default_app).strip(),
                "text": match["query"].strip(),
            }
    return None


def wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


class GuiOperator:
    def __init__(self):
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self._pg = None
        self.deadline = 0.0
        self.focused_window = None
        self.stop_reason = None

    def backend(self):
        if wayland():
            raise RuntimeError(
                "Controle de mouse/teclado requer Ubuntu on Xorg (X11). "
                "Wayland não permite controle confiável com PyAutoGUI. "
                "A pesquisa no navegador continua disponível via URL."
            )
        if self._pg is None:
            import pyautogui

            self._pg = pyautogui
        self._pg.FAILSAFE = True
        self._pg.PAUSE = 0.15
        return self._pg

    def check(self):
        if self.stopped.is_set():
            raise RuntimeError(
                "Automação pausada. Diga reativar automação ou use o botão Reativar."
            )
        if self.deadline and time.monotonic() > self.deadline:
            self.stopped.set()
            raise RuntimeError("Automação interrompida: limite de 30 segundos.")
        self.backend().failSafeCheck()
        if self.focused_window is not None:
            from Xlib.display import Display

            display = Display()
            try:
                prop = display.screen().root.get_full_property(
                    display.intern_atom("_NET_ACTIVE_WINDOW"),
                    0,
                )
                if prop is None or prop.value[0] != self.focused_window:
                    self.stopped.set()
                    raise RuntimeError(
                        "A janela perdeu o foco; automação interrompida."
                    )
            finally:
                display.close()

    @contextmanager
    def control(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Outra automação está em andamento.")
        done = threading.Event()
        watcher = None
        try:
            pg = self.backend()
            self.deadline = time.monotonic() + 30
            self.focused_window = None
            self.check()

            def monitor():
                while not done.wait(0.03):
                    try:
                        if tuple(pg.position()) in pg.FAILSAFE_POINTS:
                            self.stopped.set()
                            return
                    except Exception:
                        self.stopped.set()
                        return

            watcher = threading.Thread(target=monitor, daemon=True)
            watcher.start()
            yield
            self.check()
        except Exception as exc:
            # A missing app or unsupported Wayland action must not stop every
            # future request. Emergency/focus/deadline stops remain latched.
            fail_safe = getattr(self._pg, "FailSafeException", None)
            if self.stopped.is_set() or (
                isinstance(fail_safe, type) and isinstance(exc, fail_safe)
            ):
                self.stopped.set()
                self.stop_reason = str(exc)
            raise
        finally:
            done.set()
            if watcher:
                watcher.join(timeout=0.2)
            self.deadline = 0
            self.focused_window = None
            self.lock.release()

    def windows(self) -> list[dict]:
        self.backend()
        from Xlib.display import Display

        display = Display()
        try:
            root = display.screen().root
            prop = root.get_full_property(
                display.intern_atom("_NET_CLIENT_LIST_STACKING"),
                0,
            )
            result = []
            for window_id in reversed(list(prop.value) if prop else []):
                window = display.create_resource_object("window", int(window_id))
                try:
                    title = window.get_full_property(
                        display.intern_atom("_NET_WM_NAME"),
                        0,
                    )
                    name = (
                        bytes(title.value).decode("utf-8", "replace")
                        if title
                        else str(window.get_wm_name() or "")
                    )
                    result.append(
                        {
                            "id": int(window_id),
                            "title": name[:256],
                            "class": " ".join(window.get_wm_class() or ()),
                        }
                    )
                except Exception:
                    continue  # A window may close while enumerating it.
            return result
        finally:
            display.close()

    @staticmethod
    def matches(window: dict, app: str) -> bool:
        def compact(value):
            return re.sub(r"[^\w]", "", value.casefold())

        return bool(compact(app)) and compact(app) in compact(
            window["title"] + " " + window["class"]
        )

    def focus(self, app: str, timeout: float = 8) -> dict:
        from Xlib import X, protocol
        from Xlib.display import Display

        if not app.strip():
            raise ValueError("Informe o nome da janela em app.")
        end = time.monotonic() + timeout
        self.focused_window = None
        while time.monotonic() < end:
            self.check()
            windows = [w for w in self.windows() if self.matches(w, app)]
            if windows:
                target = windows[0]
                display = Display()
                try:
                    root = display.screen().root
                    window = display.create_resource_object("window", target["id"])
                    window.map()
                    event = protocol.event.ClientMessage(
                        window=window,
                        client_type=display.intern_atom("_NET_ACTIVE_WINDOW"),
                        data=(32, [2, X.CurrentTime, 0, 0, 0]),
                    )
                    root.send_event(
                        event,
                        event_mask=(
                            X.SubstructureRedirectMask | X.SubstructureNotifyMask
                        ),
                    )
                    display.flush()
                    for _ in range(10):
                        self.check()
                        active = root.get_full_property(
                            display.intern_atom("_NET_ACTIVE_WINDOW"),
                            0,
                        )
                        if active is not None and active.value[0] == target["id"]:
                            self.focused_window = target["id"]
                            return target
                        time.sleep(0.05)
                finally:
                    display.close()
            time.sleep(0.1)
        raise RuntimeError(f"Não consegui confirmar o foco da janela: {app}")

    def type_text(self, text: str):
        if not isinstance(text, str) or not text or len(text) > 2000:
            raise ValueError("Informe entre 1 e 2000 caracteres.")
        if any(ord(char) < 32 and char not in "\n\t" for char in text):
            raise ValueError("Texto contém caracteres de controle não permitidos.")
        pg = self.backend()
        if text.isascii():
            for char in text:
                self.check()
                # One character at a time keeps the failsafe responsive.
                pg.write(char, interval=0.02, _pause=False)
        else:
            import pyperclip

            # xclip/xsel is needed on Linux; fail before touching the keyboard
            # if no supported clipboard provider is available.
            pyperclip.copy(text)
            self.check()
            pg.hotkey("ctrl", "v")

    def search(self, app: str, text: str) -> dict:
        from openjarvis.tools.open_app import OpenAppTool

        if not isinstance(text, str) or not 1 <= len(text) <= 1500:
            raise ValueError("A pesquisa deve ter entre 1 e 1500 caracteres.")
        if any(ord(char) < 32 for char in text):
            raise ValueError("Informe a consulta em uma única linha, sem controles.")
        url = "https://www.google.com/search?q=" + quote_plus(text)
        if self.stopped.is_set():
            raise RuntimeError(
                "Automação pausada. Diga reativar automação ou use o botão Reativar."
            )
        if wayland():
            result = OpenAppTool().execute(app=app, url=url)
            if not result.success:
                raise RuntimeError(json.loads(result.content)["message"])
            return {
                "message": "Abertura da pesquisa solicitada ao navegador.",
                "method": "browser_url",
                "app": app,
            }
        with self.control():
            result = OpenAppTool().execute(app=app)
            if not result.success:
                raise RuntimeError(json.loads(result.content)["message"])
            launched_app = json.loads(result.content).get("app", app)
            self.focus(launched_app, timeout=15)
            self.check()
            self.backend().hotkey("ctrl", "l")
            self.type_text(text)  # Preserve the exact query in the address bar.
            self.check()
            self.backend().press("enter")
            return {
                "message": "Pesquisa enviada pela barra de endereços.",
                "method": "gui",
                "app": app,
            }

    def execute(self, action: str, **params) -> dict:
        if action == "stop":
            from openjarvis.operators.browser_operator import get_browser_worker

            get_browser_worker().stopped.set()
            self.stopped.set()
            self.stop_reason = "Parada solicitada pelo usuário."
            return {"message": "Automação de desktop interrompida."}
        if action == "resume":
            from openjarvis.operators.browser_operator import get_browser_worker

            if (
                get_browser_worker().lock.locked()
                or get_browser_worker().active.is_set()
            ):
                raise RuntimeError(
                    "Aguarde a navegação atual encerrar antes de rearmar."
                )
            if self.lock.locked():
                raise RuntimeError(
                    "Aguarde a automação atual encerrar antes de rearmar."
                )
            if not wayland():
                self.backend().failSafeCheck()
            self.stopped.clear()
            self.stop_reason = None
            get_browser_worker().stopped.clear()
            return {"message": "Automação de desktop rearmada."}
        if action == "browser_search":
            return self.search(params.get("app", "Firefox"), params.get("text", ""))
        with self.control():
            pg = self.backend()
            if action == "windows":
                return {"message": "Janelas encontradas.", "windows": self.windows()}
            if action == "focus":
                return {
                    "message": "Janela focada.",
                    "window": self.focus(params.get("app", "")),
                }
            if action in {"move", "click"}:
                x, y = params.get("x"), params.get("y")
                width, height = pg.size()
                if (
                    type(x) is not int
                    or type(y) is not int
                    or not 0 <= x < width
                    or not 0 <= y < height
                ):
                    raise ValueError("Coordenadas fora da tela principal.")
                if (x, y) in pg.FAILSAFE_POINTS:
                    raise ValueError(
                        "Não é permitido mover para um canto de emergência."
                    )
                pg.moveTo(x, y, duration=0.3)
                self.check()
                if action == "click":
                    pg.click(button="left")
                return {
                    "message": "Cursor movido."
                    if action == "move"
                    else "Clique realizado."
                }
            if action == "type":
                self.focus(params.get("app", ""))
                self.type_text(params.get("text", ""))
                return {"message": "Texto digitado na janela selecionada."}
            if action == "screenshot":
                root = Path(__file__).resolve().parents[3]
                folder = root / ".runtime/gui/screenshots"
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                image = pg.screenshot()
                try:
                    self.check()
                    path = folder / f"{uuid.uuid4().hex}.png"
                    image.thumbnail((1280, 960))
                    image.save(path)
                    path.chmod(0o600)
                finally:
                    image.close()
                return {"message": "Captura salva localmente.", "path": str(path)}
            raise ValueError("Ação de GUI desconhecida.")


@lru_cache(maxsize=1)
def get_gui_operator() -> GuiOperator:
    return GuiOperator()


@ToolRegistry.register("gui_control")
class GuiControlTool(BaseTool):
    tool_id = "gui_control"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Controla o desktop: windows, focus, move, click, type, screenshot, "
                "browser_search, stop e resume. Pesquise qualquer tema, passando "
                "a query literal, sem reescrever. Confirme apenas o resultado real. "
                "Mouse/teclado requerem X11; Wayland usa browser_search via URL. "
                "Stop interrompe e bloqueia novas ações até resume."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "windows",
                            "focus",
                            "move",
                            "click",
                            "type",
                            "screenshot",
                            "browser_search",
                            "stop",
                            "resume",
                        ],
                    },
                    "app": {"type": "string"},
                    "text": {"type": "string", "maxLength": 2000},
                    "query": {"type": "string", "maxLength": 1500},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            category="system",
            required_capabilities=["code:execute"],
            timeout_seconds=35,
        )

    def execute(self, **params) -> ToolResult:
        try:
            query = params.pop("query", None)
            if query is not None:
                if params.get("action") != "browser_search":
                    raise ValueError("query só pode ser usada em browser_search.")
                if "text" in params and params["text"] != query:
                    raise ValueError("query e text devem conter a mesma consulta.")
                params["text"] = query
            result = get_gui_operator().execute(**params)
            return ToolResult(
                self.tool_id, json.dumps(result, ensure_ascii=False), success=True
            )
        except Exception as exc:
            return ToolResult(
                self.tool_id,
                json.dumps({"message": str(exc)}, ensure_ascii=False),
                success=False,
            )
