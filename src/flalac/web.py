"""Web UI and small JSON API."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__
from .runner import Runner
from .sync import Engine

LYRICS_LABELS = {
    "lrclib": "LRCLIB",
    "lrclib-synced": "LRCLIB synced",
    "lrc": ".lrc",
    "lrc-synced": ".lrc synced",
    "edited-synced": "edited by you",
    "txt": ".txt",
    "tag": "file tag",
    "edited": "edited by you",
    "instrumental": "instrumental",
    "none": "none",
    None: "—",
}
COOKIE = "flalac_token"
OPEN_PATHS = ("/health", "/static", "/login")


@dataclass
class Album:
    folder: str
    tracks: list = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for t in self.tracks if t.status == "error")

    @property
    def without_lyrics(self) -> int:
        return sum(1 for t in self.tracks if t.lyrics_source in (None, "none"))


def _albums(engine: Engine, view: str, query: str) -> list[Album]:
    grouped: dict[str, Album] = defaultdict(lambda: Album(""))
    needle = query.casefold().strip()
    for track in engine.db.tracks().values():
        if needle and needle not in track.rel.casefold():
            continue
        if view == "problems" and track.status != "error":
            continue
        if view == "lyrics" and track.lyrics_source not in (None, "none"):
            continue
        folder = str(PurePosixPath(track.rel).parent)
        album = grouped[folder]
        album.folder = folder
        album.tracks.append(track)
    albums = sorted(grouped.values(), key=lambda a: a.folder.casefold())
    for album in albums:
        album.tracks.sort(key=lambda t: t.rel.casefold())
    return albums


def _summary(engine: Engine, runner: Runner | None) -> dict:
    tracks = engine.db.tracks().values()
    latest = engine.db.events(1)
    return {
        "version": __version__,
        "phase": engine.status["phase"],
        "done": engine.status["done"],
        "total": engine.status["total"],
        "current": engine.status["current"],
        "held_deletes": engine.status["held_deletes"],
        "last_pass": engine.status["last_pass"],
        "tracks": len(tracks),
        "synced": sum(1 for t in tracks if t.status == "synced"),
        "errors": sum(1 for t in tracks if t.status == "error"),
        "watching": bool(runner and runner.watching),
        "dry_run": engine.s.dry_run,
        "lyrics_style": engine.lyrics_style,
        "latest": dict(latest[0]) if latest else None,
    }


def _clock(ts: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(ts)) if ts else "—"


class TokenGate(BaseHTTPMiddleware):
    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        if not self.token or request.url.path.startswith(OPEN_PATHS):
            return await call_next(request)
        sent = request.cookies.get(COOKIE, "")
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            sent = header[7:]
        if hmac.compare_digest(sent.encode(), self.token.encode()):
            return await call_next(request)
        if request.url.path.startswith("/api"):
            return JSONResponse({"error": "unauthorised"}, status_code=401)
        return RedirectResponse("/login", status_code=303)


def create_app(engine: Engine, runner: Runner | None = None) -> Starlette:
    env = Environment(loader=PackageLoader("flalac"), autoescape=select_autoescape())
    env.filters["clock"] = _clock
    env.globals["lyrics_label"] = lambda source: LYRICS_LABELS.get(source, source)

    def page(name: str, request: Request, **context) -> HTMLResponse:
        context |= {"request": request, "s": _summary(engine, runner)}
        return HTMLResponse(env.get_template(name).render(**context))

    async def library(request: Request) -> HTMLResponse:
        view = request.query_params.get("view", "all")
        query = request.query_params.get("q", "")
        template = "_library.html" if request.headers.get("hx-request") else "library.html"
        return page(template, request, albums=_albums(engine, view, query), view=view, q=query)

    async def status(request: Request) -> HTMLResponse:
        return page("_status.html", request)

    async def log(request: Request) -> HTMLResponse:
        return page("log.html", request, events=engine.db.events(500))

    async def scan(request: Request) -> Response:
        if runner:
            runner.trigger()
        if request.headers.get("hx-request"):
            return page("_status.html", request)
        return RedirectResponse("/", status_code=303)

    async def confirm_deletes(request: Request) -> Response:
        engine.confirm_deletes()
        return await scan(request)

    async def lyrics_style(request: Request) -> Response:
        form = await request.form()
        style = str(form.get("style", ""))
        if style in ("plain", "synced") and style != engine.lyrics_style:
            engine.set_lyrics_style(style)
            engine.db.event("lyrics-style", None, f"switched to {style}; refreshing lyrics")
            if runner:
                runner.trigger()
        if request.headers.get("hx-request"):
            return page("_style.html", request)
        return RedirectResponse("/", status_code=303)

    async def health(request: Request) -> JSONResponse:
        ok = engine.status["phase"] != "paused"
        return JSONResponse(
            {"ok": ok, "phase": engine.status["phase"]}, status_code=200 if ok else 503
        )

    async def api_status(request: Request) -> JSONResponse:
        return JSONResponse(_summary(engine, runner))

    async def login(request: Request) -> Response:
        if request.method == "POST":
            form = await request.form()
            token = str(form.get("token", ""))
            if engine.s.auth_token and hmac.compare_digest(
                token.encode(), engine.s.auth_token.encode()
            ):
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(
                    COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365
                )
                return response
            return page("login.html", request, failed=True)
        return page("login.html", request, failed=False)

    static = Path(__file__).parent / "static"
    routes = [
        Route("/", library),
        Route("/status", status),
        Route("/log", log),
        Route("/scan", scan, methods=["POST"]),
        Route("/deletes/confirm", confirm_deletes, methods=["POST"]),
        Route("/lyrics-style", lyrics_style, methods=["POST"]),
        Route("/health", health),
        Route("/api/status", api_status),
        Route("/login", login, methods=["GET", "POST"]),
        Mount("/static", StaticFiles(directory=static), name="static"),
    ]
    return Starlette(routes=routes, middleware=[Middleware(TokenGate, token=engine.s.auth_token)])
