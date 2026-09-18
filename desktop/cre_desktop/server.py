"""Runs the FastAPI backend inside the launcher process.

- Binds 127.0.0.1 on a port the OS picks (port 0) and hands the bound socket
  to uvicorn, so there's no pick-then-bind race and never a hardcoded port.
- Runs uvicorn on a thread of this process: when the window closes the whole
  process exits, so there's no separate Python process to orphan.
- Wraps the ASGI app in an access gate. Any web page open in the user's
  browser can send requests to 127.0.0.1:<port>; the gate only admits the
  desktop window, which receives a per-launch token once and holds it as a
  SameSite=Strict, HttpOnly cookie. It also rejects foreign Host headers
  (DNS rebinding). Dev (uvicorn/vite) never goes through this module.
"""

import logging
import secrets
import socket
import threading
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

import uvicorn

log = logging.getLogger(__name__)

AUTH_PATH = "/__desktop_auth"
COOKIE_NAME = "cre_desktop_token"


class AccessGate:
    def __init__(self, app, token: str, port: int):
        self.app = app
        self.token = token
        self.allowed_hosts = {f"127.0.0.1:{port}".encode(), f"localhost:{port}".encode()}

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        if headers.get(b"host") not in self.allowed_hosts:
            return await _plain(send, 403, "Forbidden host")

        if scope["path"] == AUTH_PATH:
            query = parse_qs(scope.get("query_string", b"").decode())
            if not secrets.compare_digest(query.get("t", [""])[0], self.token):
                return await _plain(send, 403, "Invalid token")
            cookie = f"{COOKIE_NAME}={self.token}; Path=/; HttpOnly; SameSite=Strict"
            await send({
                "type": "http.response.start",
                "status": 303,
                "headers": [(b"location", b"/"), (b"set-cookie", cookie.encode())],
            })
            return await send({"type": "http.response.body", "body": b""})

        jar = SimpleCookie()
        jar.load(headers.get(b"cookie", b"").decode("latin-1"))
        presented = jar[COOKIE_NAME].value if COOKIE_NAME in jar else ""
        if not secrets.compare_digest(presented, self.token):
            return await _plain(send, 403, "This server only answers the CRE Underwriting window.")
        return await self.app(scope, receive, send)


async def _plain(send, status: int, text: str):
    body = text.encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
    })
    await send({"type": "http.response.body", "body": body})


class BackendServer:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port: int = self.sock.getsockname()[1]
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.error: BaseException | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def entry_url(self) -> str:
        return f"{self.base_url}{AUTH_PATH}?t={self.token}"

    def start(self, asgi_app) -> None:
        config = uvicorn.Config(
            AccessGate(asgi_app, self.token, self.port),
            # Pure-Python loop/protocol: the optional native uvloop/httptools
            # are loaded by name at runtime, which a frozen build can miss.
            loop="asyncio",
            http="h11",
            ws="none",
            lifespan="on",
            log_config=None,  # the launcher's logging config applies
            access_log=False,  # the backend logs every request itself
        )
        self._server = uvicorn.Server(config)
        # uvicorn installs signal handlers only on the main thread; we run
        # it on a worker thread and quit via should_exit instead.
        self._thread = threading.Thread(target=self._run, name="backend", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._server is not None
        try:
            self._server.run(sockets=[self.sock])
        except BaseException as exc:  # noqa: BLE001 — surfaced in the window
            log.exception("Backend server crashed")
            self.error = exc

    def wait_until_started(self, timeout: float) -> bool:
        """True once uvicorn is accepting connections; False on crash/timeout."""
        assert self._server is not None and self._thread is not None
        waited = 0.0
        while waited < timeout:
            if self._server.started:
                return True
            if not self._thread.is_alive():
                return False
            threading.Event().wait(0.05)
            waited += 0.05
        return False

    def stop(self, timeout: float = 10.0) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)
        try:
            self.sock.close()
        except OSError:
            pass
