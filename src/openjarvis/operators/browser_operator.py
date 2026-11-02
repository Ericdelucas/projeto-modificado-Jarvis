"""Observe/plan/act browser automation; no site-specific scripts or model JS."""

from __future__ import annotations

import atexit
import base64
import io
import json
import math
import os
import queue
import threading
from concurrent.futures import Future, TimeoutError
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.operators.computer_use.agent import run_task
from openjarvis.tools._stubs import BaseTool, ToolSpec

DOM_SNAPSHOT = """() => {
  document.querySelectorAll('[data-jarvis-ref]').forEach(e=>e.removeAttribute('data-jarvis-ref'));
  const nodes = [...document.querySelectorAll(
    'a[href],button,input,textarea,select,[role="button"],[role="link"],[role="tab"],[contenteditable="true"]'
  )].filter(e=>e.getClientRects().length &&
    getComputedStyle(e).visibility !== 'hidden');
  let count=0, budget=6500; const elements=[];
  for (const el of nodes) {
    if (count>=80 || budget<150) break;
    const ref='e'+(++count); el.setAttribute('data-jarvis-ref',ref);
    const type=(el.getAttribute('type')||'').toLowerCase();
    const item={ref,tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',
      name:(el.getAttribute('aria-label')||el.innerText||el.getAttribute('placeholder')||el.title||el.name||'').trim().slice(0,150),
      href:(el.getAttribute('href')||'').slice(0,300),type,
      value:type==='password'?'[redacted]':(el.value||'').slice(0,120),
      selected:el.getAttribute('aria-selected')||el.getAttribute('aria-current')||''};
    const size=JSON.stringify(item).length; if(size>budget) break;
    elements.push(item); budget-=size;
  }
  return {url:location.href,title:document.title,
    text:(document.body?.innerText||'').slice(0,2400),elements,
    videos:[...document.querySelectorAll('video')].slice(0,3).map(v=>({paused:v.paused,currentTime:v.currentTime}))};
}"""


class BrowserSession:
    """All Playwright calls run on the one owning worker thread."""

    def __init__(self, headless=False, profile=None):
        self.headless = headless
        self.profile = profile
        self.driver = self.context = self.page = None
        self.refs: set[str] = set()
        self.frame_size = None

    def start(self):
        if self.context is not None:
            try:
                self.page.title()
                return
            except Exception:
                self.close()
        from playwright.sync_api import sync_playwright

        from openjarvis.tools.open_app import launch_environment

        root = Path(__file__).resolve().parents[3]
        os.environ.setdefault(
            "PLAYWRIGHT_BROWSERS_PATH", str(root / ".runtime/playwright")
        )
        profile = self.profile or root / ".runtime/browser/firefox-profile"
        Path(profile).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.driver = sync_playwright().start()
        self.context = self.driver.firefox.launch_persistent_context(
            str(profile),
            headless=self.headless,
            env=launch_environment(),
            viewport={"width": 1152, "height": 768},
            locale="pt-BR",
            accept_downloads=False,
        )
        self.context.set_default_timeout(5000)
        self.context.set_default_navigation_timeout(15000)
        self.page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )
        self.page.on("dialog", lambda dialog: dialog.dismiss())
        self.page.bring_to_front()

    def capture_frame(self):
        """Viewport only, JPEG <= 960x640; no frame files/history/full-page shots."""
        from PIL import Image

        self.page.bring_to_front()
        raw = self.page.screenshot(
            type="jpeg", quality=60, full_page=False, timeout=5000
        )
        try:
            with io.BytesIO(raw) as source, Image.open(source) as image:
                image.thumbnail((960, 640))
                with io.BytesIO() as output:
                    image.save(output, format="JPEG", quality=60)
                    if output.tell() > 512 * 1024:
                        raise ValueError("Captura excedeu o limite de 512 KiB.")
                    self.frame_size = image.size
                    return base64.b64encode(output.getvalue()).decode("ascii")
        finally:
            del raw

    def close(self):
        try:
            if self.context:
                self.context.close()
        finally:
            if self.driver:
                self.driver.stop()
            self.driver = self.context = self.page = None

    def observe(self) -> dict:
        if self.page.is_closed():
            pages = [page for page in self.context.pages if not page.is_closed()]
            self.page = pages[-1] if pages else self.context.new_page()
        from playwright.sync_api import Error

        for attempt in range(3):
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                snapshot = self.page.evaluate(DOM_SNAPSHOT)
                break
            except Error as exc:
                if attempt == 2 or not any(
                    term in str(exc)
                    for term in (
                        "Execution context was destroyed",
                        "navigation",
                        "Timeout",
                    )
                ):
                    raise
                self.page.wait_for_timeout(250)
        self.refs = {element["ref"] for element in snapshot["elements"]}
        return snapshot

    def act(self, action: dict):
        kind = action.get("action")
        page = self.page
        page.bring_to_front()
        if kind == "navigate":
            url = action.get("url", "")
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or "." not in parsed.hostname
                or "..." in url
            ):
                raise ValueError("Só URLs HTTP(S) podem ser abertas.")
            page.goto(url, wait_until="domcontentloaded")
        elif kind == "click" and "x" in action:
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
                raise ValueError("Clique exige coordenadas de uma captura atual.")
            viewport = page.viewport_size
            page.mouse.click(
                x * viewport["width"] / self.frame_size[0],
                y * viewport["height"] / self.frame_size[1],
            )
        elif kind == "type":
            text = action.get("text")
            if not isinstance(text, str) or len(text) > 4000:
                raise ValueError("Texto inválido para digitação.")
            if page.locator('input[type="password"]:focus').count():
                raise ValueError("Preencha a senha manualmente no navegador.")
            page.keyboard.insert_text(text)
        elif kind == "press" and not action.get("ref"):
            if action.get("key") not in {
                "Enter",
                "Tab",
                "Escape",
                "ArrowDown",
                "ArrowUp",
            }:
                raise ValueError("Tecla não suportada nesta ação.")
            page.keyboard.press(action["key"])
        elif kind in {"click", "fill", "press"}:
            ref = action.get("ref")
            if ref not in self.refs:
                raise ValueError("Referência inexistente; observe a página novamente.")
            locator = page.locator(f'[data-jarvis-ref="{ref}"]')
            if kind == "click":
                locator.click()
            elif kind == "fill":
                value = action.get("text", "")
                if not isinstance(value, str) or len(value) > 4000:
                    raise ValueError("Texto inválido para preenchimento.")
                if locator.get_attribute("type") == "password":
                    raise ValueError("Preencha a senha manualmente no navegador.")
                locator.fill(value)
            else:
                key = action.get("key")
                if key not in {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp"}:
                    raise ValueError("Tecla não suportada nesta ação.")
                locator.press(key)
        elif kind == "scroll":
            page.mouse.wheel(0, 650 if action.get("direction") == "down" else -650)
        elif kind == "back":
            page.go_back(wait_until="domcontentloaded")
        elif kind != "wait":
            raise ValueError("Ação de navegador desconhecida.")
        delay = action.get("seconds", 1) if kind == "wait" else 0.5
        if type(delay) not in {int, float} or not math.isfinite(delay):
            raise ValueError("Espera inválida.")
        page.wait_for_timeout(max(0.1, min(delay, 5)) * 1000)
        pages = [item for item in self.context.pages if not item.is_closed()]
        if pages and pages[-1] != self.page:
            self.page = pages[-1]
        self.refs.clear()  # Every action requires fresh evidence before another.
        self.frame_size = None


class BrowserWorker:
    def __init__(self):
        self.queue = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.active = threading.Event()
        self.thread = None

    def _work(self):
        session = BrowserSession()
        try:
            while True:
                job = self.queue.get()
                if job is None:
                    break
                future, task, history = job
                if not future.set_running_or_notify_cancel():
                    continue
                engine = None
                self.active.set()
                try:
                    from openjarvis.core.config import load_config
                    from openjarvis.engine.ollama import OllamaEngine
                    from openjarvis.operators.computer_use.agent import check_memory

                    cfg = load_config()
                    options = cfg.computer_use
                    vision = bool(options.vision_model.strip())
                    memory_floor = max(
                        512,
                        options.min_available_mb,
                        options.vision_min_available_mb if vision else 0,
                    )
                    check_memory(memory_floor)
                    session.start()
                    engine = OllamaEngine(host=cfg.engine.ollama.host, timeout=25)
                    result = run_task(
                        session,
                        task,
                        history,
                        engine,
                        options.vision_model.strip()
                        if vision
                        else cfg.programacao.general_model,
                        self.stopped,
                        max_steps=max(1, min(options.max_steps, 40)),
                        seconds=max(5, min(options.timeout, 180)),
                        vision=vision,
                        num_ctx=options.num_ctx,
                        min_available_mb=max(512, options.min_available_mb),
                    )
                    future.set_result(result)
                except Exception as exc:
                    future.set_exception(exc)
                finally:
                    self.active.clear()
                    if engine:
                        engine.close()
                    # Preserve the visible result, but do not accumulate tabs from
                    # previous tasks in the one persistent browser context.
                    if (
                        session.context
                        and session.page
                        and not session.page.is_closed()
                    ):
                        for page in session.context.pages:
                            if page != session.page:
                                page.close()
        finally:
            session.close()

    def run(self, task, history):
        if self.stopped.is_set():
            raise RuntimeError("Navegação parada. Use reativar automação.")
        if self.active.is_set():
            raise RuntimeError("Uma navegação ainda está encerrando.")
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Uma navegação já está em andamento.")
        try:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(
                    target=self._work, daemon=True, name="jarvis-browser"
                )
                self.thread.start()
            future = Future()
            self.queue.put_nowait((future, task, history))
            try:
                return future.result(timeout=215)
            except TimeoutError as exc:
                self.stopped.set()
                raise RuntimeError(
                    "Navegação excedeu o tempo máximo e foi interrompida."
                ) from exc
        finally:
            self.lock.release()

    def close(self):
        self.stopped.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass


@lru_cache(maxsize=1)
def get_browser_worker():
    worker = BrowserWorker()
    atexit.register(worker.close)
    return worker


@ToolRegistry.register("browser_task")
class BrowserTaskTool(BaseTool):
    tool_id = "browser_task"

    @property
    def spec(self):
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Executa uma tarefa completa de navegação em várias etapas, "
                "observando elementos reais da página. Passe TODO o pedido, "
                "sem reduzir a uma busca."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "maxLength": 4000},
                    "context": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            category="system",
            required_capabilities=["code:execute"],
            timeout_seconds=230,
        )

    def execute(self, task="", context=None, **kwargs):
        try:
            if not isinstance(task, str) or not task.strip() or len(task) > 4000:
                raise ValueError(
                    "Informe a tarefa de navegação completa (até 4000 caracteres)."
                )
            result = get_browser_worker().run(
                task, [str(item)[-800:] for item in (context or [])[-4:]]
            )
            return ToolResult(
                self.tool_id,
                json.dumps(result, ensure_ascii=False),
                success=result["status"] == "completed",
            )
        except Exception as exc:
            return ToolResult(
                self.tool_id,
                json.dumps(
                    {"status": "failed", "message": str(exc)}, ensure_ascii=False
                ),
                success=False,
            )
