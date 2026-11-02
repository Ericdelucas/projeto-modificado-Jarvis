"""Local execution only. All methods are called on one dedicated worker thread."""

from __future__ import annotations

import base64
import io
import math
import time
from pathlib import Path


class WebBackend:
    def __init__(self, config, guard):
        self.config, self.guard = config, guard
        self.session = None

    def start(self):
        from openjarvis.operators.browser_operator import BrowserSession

        self.guard.check()
        profile = Path(__file__).resolve().parents[3] / ".runtime/jarvis-core/firefox"
        self.session = BrowserSession(headless=self.config.headless, profile=profile)
        self.session.start()

    def observe(self):
        self.guard.check()
        return self.session.observe(), None  # Never capture/send images for web.

    def act(self, action):
        self.guard.check()
        if (
            action.get("action")
            not in {"navigate", "click", "fill", "press", "scroll", "back", "wait"}
            or "x" in action
            or "y" in action
        ):
            raise ValueError("Web requer ações DOM com referências observadas.")
        self.session.act(action)

    def close(self):
        if self.session:
            self.session.close()


class DesktopBackend:
    def __init__(self, config, guard):
        self.config, self.guard = config, guard
        self.gui = None
        self.frame_size = self.screen_size = None
        self.target = ""

    def start(self):
        from openjarvis.operators.gui_operator import GuiOperator, wayland

        if wayland():
            raise RuntimeError(
                "Desktop nativo indisponível em Wayland: requer um "
                "adaptador RemoteDesktop/ScreenCast autorizado. "
                "Use X11 para PyAutoGUI; o modo web funciona em Wayland."
            )
        self.gui = GuiOperator()
        self.gui.stopped = self.guard.stopped
        self.gui.backend()  # Fail before the first remote screenshot request.
        self.guard.check()

    def observe(self):
        self.guard.check()
        image = self.gui.backend().screenshot()
        try:
            self.screen_size = image.size
            image.thumbnail((960, 640))
            self.frame_size = image.size
            with io.BytesIO() as buffer:
                with image.convert("RGB") as rgb:
                    rgb.save(buffer, format="JPEG", quality=55)
                if buffer.tell() > 512 * 1024:
                    raise ValueError("Captura excedeu 512 KiB.")
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            self.guard.check()
            return {
                "windows": self.gui.windows()[:30],
                "image_size": self.frame_size,
            }, encoded
        finally:
            image.close()

    def _point(self, action):
        x, y = action.get("x"), action.get("y")
        if (
            not self.frame_size
            or type(x) not in {int, float}
            or type(y) not in {int, float}
            or not math.isfinite(x)
            or not math.isfinite(y)
            or not 0 <= x < self.frame_size[0]
            or not 0 <= y < self.frame_size[1]
        ):
            raise ValueError(
                "Coordenadas exigem uma captura atual e devem estar na imagem."
            )
        return (
            int(x * self.screen_size[0] / self.frame_size[0]),
            int(y * self.screen_size[1] / self.frame_size[1]),
        )

    def act(self, action):
        self.guard.check()
        kind = action.get("action")
        if kind == "open_app":
            from openjarvis.tools.open_app import OpenAppTool

            result = OpenAppTool().execute(app=action.get("app", ""))
            if not result.success:
                raise RuntimeError("Falha ao iniciar o aplicativo solicitado.")
        elif kind == "wait":
            seconds = action.get("seconds", 1)
            if type(seconds) not in {int, float} or not math.isfinite(seconds):
                raise ValueError("Tempo de espera inválido.")
            self.guard.stopped.wait(max(0.1, min(seconds, 5)))
        else:
            with self.gui.control():
                pg = self.gui.backend()
                if kind == "focus":
                    self.target = action.get("app", "")
                    self.gui.focus(self.target)
                else:
                    if not self.target:
                        raise ValueError(
                            "Foque explicitamente o aplicativo antes de interagir."
                        )
                    self.gui.focus(self.target)
                    if kind in {"click", "move"}:
                        x, y = self._point(action)
                        start_x, start_y = pg.position()
                        for step in range(1, 11):
                            self.guard.check()
                            self.gui.check()
                            pg.moveTo(
                                start_x + (x - start_x) * step / 10,
                                start_y + (y - start_y) * step / 10,
                                duration=0,
                                _pause=False,
                            )
                            time.sleep(0.015)
                        self.guard.check()
                        if kind == "click":
                            pg.click(_pause=False)
                    elif kind == "type":
                        self.gui.type_text(action.get("text", ""))
                    elif kind == "press":
                        keys = {
                            "Enter": ["enter"],
                            "Tab": ["tab"],
                            "Escape": ["esc"],
                            "Ctrl+L": ["ctrl", "l"],
                        }
                        if action.get("key") not in keys:
                            raise ValueError("Atalho não suportado.")
                        pg.hotkey(*keys[action["key"]], _pause=False)
                    elif kind == "scroll":
                        clicks = action.get("clicks", -3)
                        if type(clicks) is not int or not -10 <= clicks <= 10:
                            raise ValueError("Rolagem deve estar entre -10 e 10.")
                        pg.scroll(clicks, _pause=False)
                    else:
                        raise ValueError("Ação de desktop não suportada.")
        self.frame_size = None
        self.guard.check()

    def close(self):
        if self.gui and self.gui._pg:
            pg = self.gui._pg
            for key in ("ctrl", "alt", "shift", "win"):
                try:
                    pg.keyUp(key, _pause=False)
                except Exception:
                    pass
