"""Read-only access to a logged-in WhatsApp Web tab in the user's Firefox.

Firefox must run with ``--remote-debugging-port`` so that WebDriver BiDi is
available; when Firefox is closed, it is started that way and the WhatsApp tab
is opened if missing.  The page is only read: no clicks, no typing, so chats
are never marked as read.
"""

import json
import os
import shutil
import subprocess
import time
from itertools import count
from urllib.parse import urlparse

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

DEFAULT_BIDI_URL = "ws://127.0.0.1:9222/session"
WHATSAPP_URL = "https://web.whatsapp.com"
MAX_ITEMS = 50
MAX_TEXT = 500
LOGIN_WAIT = 20  # Seconds a freshly opened tab gets to show the chat list.

# Runs in an isolated sandbox realm: it sees the DOM but not the page's JS.
# Dates come from the browser clock, which is what WhatsApp itself displays.
_EXTRACT_JS = r"""
(() => {
  const MAX_ITEMS = %(max_items)d, MAX_TEXT = %(max_text)d;
  const cut = s => (s || "").trim().slice(0, MAX_TEXT);
  const pad = n => String(n).padStart(2, "0");
  const d = new Date();
  const today = new Set([
    `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`,
    `${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()}`,
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
  ]);
  const side = document.querySelector("#pane-side");
  if (!side) return JSON.stringify({logged_in: false});

  const clock = /^\d{1,2}:\d{2}(\s?[AaPp]\.?\s?[Mm]\.?)?$/;
  let rows = [...side.querySelectorAll('[role="listitem"], [role="row"]')];
  rows = rows.filter(r => !rows.some(o => o !== r && o.contains(r)));
  const chats = [];
  for (const row of rows) {
    const leaves = [...row.querySelectorAll("*")]
      .filter(e => !e.children.length).map(e => e.textContent.trim());
    const time = leaves.find(t => clock.test(t));
    if (!time) continue;  // Older chats show "Ontem" or a date instead.
    const titles = [...row.querySelectorAll("span[title]")]
      .map(s => s.getAttribute("title")).filter(Boolean);
    const badge = [...row.querySelectorAll("[aria-label]")]
      .map(e => e.getAttribute("aria-label"))
      .find(l => /não lida|unread/i.test(l));
    chats.push({
      chat: cut(titles[0]),
      last_message: cut(titles.slice(1).join(" ")),
      time,
      unread: badge ? parseInt(badge, 10) || 1 : 0,
      last_from_me: !!row.querySelector('[data-icon*="check"]'),
    });
    if (chats.length >= MAX_ITEMS) break;
  }

  const main = document.querySelector("#main");
  const messages = [];
  if (main) {
    const header = main.querySelector("header span[title]");
    const chat = cut(header ? header.getAttribute("title") : "");
    for (const el of main.querySelectorAll(".message-in [data-pre-plain-text]")) {
      const m = el.getAttribute("data-pre-plain-text")
        .match(/^\[([^,\]]+),\s*([^\]]+)\]\s*(.*?):\s*$/);
      if (!m || !today.has(m[2].trim())) continue;
      const body = el.querySelector(".selectable-text") || el;
      messages.push({
        chat, time: m[1].trim(), author: cut(m[3]), text: cut(body.innerText),
      });
    }
  }
  return JSON.stringify({
    logged_in: true, chats, open_chat_messages: messages.slice(-MAX_ITEMS),
  });
})()
""" % {"max_items": MAX_ITEMS, "max_text": MAX_TEXT}


class WhatsAppUnavailable(Exception):
    """Firefox or the WhatsApp Web tab cannot be reached."""


class WhatsAppWebClient:
    def __init__(
        self,
        url: str | None = None,
        *,
        connector=connect,
        launcher=None,
        firefox_running=None,
        sleep=time.sleep,
        launch_timeout: float = 30,
    ):
        self.url = url or os.environ.get(
            "OPENJARVIS_FIREFOX_BIDI_URL", DEFAULT_BIDI_URL
        )
        self._connect = connector
        self._launch = launcher or _launch_firefox
        self._firefox_running = firefox_running or _firefox_running
        self._sleep = sleep
        self._launch_timeout = launch_timeout

    def today(self) -> dict:
        try:
            return self._today()
        except (OSError, WebSocketException):
            pass
        # Firefox ignores --remote-debugging-port when an instance already
        # runs, so only start it ourselves when it is closed.
        if self._firefox_running():
            raise WhatsAppUnavailable(
                "O Firefox está aberto sem a porta de depuração. Feche-o por "
                "completo; na próxima pergunta o Jarvis o abre com a porta 9222 "
                "(ou abra com 'firefox --remote-debugging-port 9222')."
            )
        try:
            self._launch(self._port())
        except OSError as exc:
            raise WhatsAppUnavailable(
                f"Não foi possível abrir o Firefox: {exc}"
            ) from exc
        deadline = time.monotonic() + self._launch_timeout
        while True:
            self._sleep(1)
            try:
                return self._today(wait_login=True)
            except (OSError, WebSocketException) as exc:
                if time.monotonic() >= deadline:
                    raise WhatsAppUnavailable(
                        "O Firefox foi aberto, mas a porta de depuração "
                        f"{self._port()} não respondeu."
                    ) from exc

    def _port(self) -> int:
        return urlparse(self.url).port or 9222

    def _today(self, *, wait_login: bool = False) -> dict:
        with self._connect(self.url, open_timeout=5, max_size=8 * 2**20) as ws:
            return self._read(_Session(ws), wait_login)

    def _read(self, session: "_Session", wait_login: bool) -> dict:
        session.call("session.new", {"capabilities": {}})
        try:
            tree = session.call("browsingContext.getTree", {})
            tab = next(
                (
                    c["context"]
                    for c in tree.get("contexts", [])
                    if c.get("url", "").startswith(WHATSAPP_URL)
                ),
                None,
            )
            if tab is None:
                tab = session.call("browsingContext.create", {"type": "tab"})["context"]
                session.call(
                    "browsingContext.navigate",
                    {"context": tab, "url": WHATSAPP_URL, "wait": "complete"},
                )
                wait_login = True
            # A freshly loaded WhatsApp needs a few seconds to show the chats.
            deadline = time.monotonic() + (LOGIN_WAIT if wait_login else 0)
            while True:
                data = self._evaluate(session, tab)
                if data["logged_in"] or time.monotonic() >= deadline:
                    break
                self._sleep(1)
        finally:
            session.call("session.end", {})
        if not data["logged_in"]:
            raise WhatsAppUnavailable(
                "O WhatsApp Web está aberto, mas não conectado (leia o QR code)."
            )
        chats, messages = data["chats"], data["open_chat_messages"]
        received = [c for c in chats if not c["last_from_me"]]
        return {
            "status": "ok" if received or messages else "empty",
            "chats_today": chats,
            "unread_total": sum(c["unread"] for c in chats),
            "open_chat_messages_today": messages,
            "note": (
                "chats_today vem da lista lateral (última mensagem de cada conversa "
                "com atividade hoje); open_chat_messages_today são as mensagens "
                "recebidas hoje na conversa aberta."
            ),
        }

    @staticmethod
    def _evaluate(session: "_Session", tab: str) -> dict:
        evaluated = session.call(
            "script.evaluate",
            {
                "expression": _EXTRACT_JS,
                "target": {"context": tab, "sandbox": "openjarvis"},
                "awaitPromise": False,
            },
        )
        if evaluated.get("type") != "success":
            raise WhatsAppUnavailable("Não foi possível ler a página do WhatsApp Web.")
        return json.loads(evaluated["result"]["value"])


def _firefox_running() -> bool:
    return (
        subprocess.run(
            ["pgrep", "-x", "firefox"], capture_output=True, check=False
        ).returncode
        == 0
    )


def _launch_firefox(port: int) -> None:
    subprocess.Popen(
        [
            shutil.which("firefox") or "firefox",
            "--remote-debugging-port",
            str(port),
            WHATSAPP_URL,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class _Session:
    def __init__(self, ws):
        self._ws = ws
        self._ids = count(1)

    def call(self, method: str, params: dict) -> dict:
        msg_id = next(self._ids)
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            reply = json.loads(self._ws.recv(timeout=20))
            if reply.get("id") != msg_id:
                continue  # Events.
            if reply.get("type") == "error":
                raise WhatsAppUnavailable(
                    f"Firefox recusou {method}: {reply.get('error')} "
                    f"{reply.get('message', '')}".strip()
                )
            return reply.get("result", {})
