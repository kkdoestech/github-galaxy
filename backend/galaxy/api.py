"""HTTP API. Builds stream progress over Server-Sent Events; results are cached."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .cache import Cache
from .config import ROOT, load_settings
from .github import GitHubClient, GitHubError, GitHubSource, Source
from .graph import SIGNALS
from .service import build, cached_galaxy, cached_raw, check_params, galaxy_from_raw

log = logging.getLogger("galaxy")
MAX_PARALLEL_BUILDS = 2
KEEPALIVE = 15.0


class Job:
    """One running build. Several browser tabs can follow the same job."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.cond = asyncio.Condition()

    async def push(self, event: str, data: dict[str, Any]) -> None:
        async with self.cond:
            self.events.append({"event": event, "data": data})
            self.cond.notify_all()

    async def follow(self) -> AsyncIterator[dict[str, Any] | None]:
        """Yield events as they arrive; None means "nothing new, send a keepalive"."""
        seen = 0
        while True:
            async with self.cond:
                try:
                    await asyncio.wait_for(
                        self.cond.wait_for(lambda n=seen: len(self.events) > n), KEEPALIVE
                    )
                except TimeoutError:
                    yield None
                    continue
                fresh = self.events[seen:]
                seen = len(self.events)
            for event in fresh:
                yield event
                if event["event"] in ("result", "error"):
                    return


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def error_body(exc: GitHubError) -> dict[str, Any]:
    return {"code": exc.code, "msg": exc.message, "reset_at": exc.reset_at}


class ReclusterBody(BaseModel):
    key: str
    k: int | None = None
    s: str = "collab"


def create_app(
    source: Source | None = None,
    cache: Cache | None = None,
    client: GitHubClient | None = None,
    serve_frontend: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = load_settings()
        app.state.settings = settings
        app.state.cache = cache or Cache(settings.cache_path)
        app.state.client = client or (None if source else GitHubClient(settings.token))
        app.state.source = source or GitHubSource(app.state.client, app.state.cache)
        app.state.jobs = {}
        app.state.slots = asyncio.Semaphore(MAX_PARALLEL_BUILDS)
        if settings.token:
            log.info("GitHub token from %s", settings.token_source)
        else:
            log.warning("No GitHub token. Set GITHUB_TOKEN in .env or log in with `gh`.")
        yield
        if app.state.client and client is None:
            await app.state.client.aclose()

    app = FastAPI(title="GitHub Galaxy", lifespan=lifespan)

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        st = request.app.state
        rate = None
        if st.client is not None and st.settings.token:
            try:
                rate = await st.client.rate_limit()
            except GitHubError:
                rate = None
        return {"ok": True, "token": bool(st.settings.token) or source is not None, "rate": rate}

    async def run_job(app: FastAPI, key: str, job: Job, params: tuple) -> None:
        st = app.state

        async def progress(event: dict[str, Any]) -> None:
            await job.push("progress", event)

        try:
            if st.slots.locked():
                await progress({"stage": "queue", "done": 0, "total": 1,
                                "msg": "Waiting for another build to finish"})
            async with st.slots:
                galaxy = await build(st.source, st.cache, *params, progress=progress)
            await job.push("result", galaxy)
        except GitHubError as exc:
            await job.push("error", error_body(exc))
        except Exception:  # pragma: no cover - logged, reported plainly
            log.exception("build failed")
            await job.push("error", {"code": "UPSTREAM", "msg": "Something went wrong while "
                                     "building. Try again.", "reset_at": None})
        finally:
            st.jobs.pop(key, None)

    @app.get("/api/galaxy/stream")
    async def stream(
        request: Request, u: str, d: int = 2, n: int = 800, s: str = "collab"
    ) -> StreamingResponse:
        st = request.app.state

        async def events() -> AsyncIterator[str]:
            try:
                check_params(u, d, n, s)
            except GitHubError as exc:
                yield sse("error", error_body(exc))
                return
            hit = cached_galaxy(st.cache, u, d, n, s)
            if hit:
                yield sse("result", hit)
                return
            key = f"{u.lower()}:{d}:{n}:{s}"
            job = st.jobs.get(key)
            if job is None:
                job = st.jobs[key] = Job()
                asyncio.create_task(run_job(request.app, key, job, (u, d, n, s)))
            async for event in job.follow():
                if event is None:
                    yield ": keepalive\n\n"
                else:
                    yield sse(event["event"], event["data"])

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/recluster")
    async def recluster(request: Request, body: ReclusterBody) -> dict[str, Any]:
        st = request.app.state
        try:
            login, depth, max_people = body.key.split(":")[:3]
            depth, max_people = int(depth), int(max_people)
        except ValueError as exc:
            raise HTTPException(400, "Bad galaxy key.") from exc
        if body.s not in SIGNALS or (body.k is not None and not 2 <= body.k <= 20):
            raise HTTPException(400, "Clusters must be 2-20 and signal collab or follow.")
        raw = cached_raw(st.cache, login, depth, max_people)
        if raw is None:
            raise HTTPException(404, "This galaxy is no longer cached. Build it again.")
        return await galaxy_from_raw(st.cache, raw, body.s, body.k)

    dist = ROOT / "frontend" / "dist"
    if serve_frontend and dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


app = create_app()
