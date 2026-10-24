"""Cache-aware build steps shared by the API and the CLI."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .cache import DAY, Cache
from .crawl import Progress, crawl
from .github import GitHubError, Source
from .graph import SIGNALS
from .models import RawGraph
from .pipeline import build_galaxy, galaxy_key

RAW_MAX_AGE = 7 * DAY
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
MIN_PEOPLE, MAX_PEOPLE = 100, 3000


def check_params(login: str, depth: int, max_people: int, signal: str) -> None:
    if not LOGIN_RE.match(login or ""):
        raise GitHubError("BAD_INPUT", "That doesn't look like a GitHub username.")
    if depth not in (1, 2, 3):
        raise GitHubError("BAD_INPUT", "Depth must be 1, 2 or 3.")
    if not MIN_PEOPLE <= max_people <= MAX_PEOPLE:
        raise GitHubError("BAD_INPUT", f"Max people must be {MIN_PEOPLE}-{MAX_PEOPLE}.")
    if signal not in SIGNALS:
        raise GitHubError("BAD_INPUT", f"Signal must be one of: {', '.join(SIGNALS)}.")


def raw_key(login: str, depth: int, max_people: int) -> str:
    return f"raw:{login.lower()}:{depth}:{max_people}"


def cached_raw(cache: Cache, login: str, depth: int, max_people: int) -> RawGraph | None:
    hit = cache.get(raw_key(login, depth, max_people), RAW_MAX_AGE)
    return RawGraph.from_dict(hit) if hit else None


def cached_galaxy(
    cache: Cache, login: str, depth: int, max_people: int, signal: str, k: int | None = None
) -> dict[str, Any] | None:
    key = galaxy_key(login, depth, max_people, signal) + (f":k{k}" if k else "")
    return cache.get(f"galaxy:{key}", RAW_MAX_AGE)


async def galaxy_from_raw(
    cache: Cache, raw: RawGraph, signal: str, k: int | None = None
) -> dict[str, Any]:
    key = galaxy_key(raw.seed, raw.depth, raw.max_people, signal) + (f":k{k}" if k else "")
    hit = cache.get(f"galaxy:{key}", RAW_MAX_AGE)
    if hit:
        return hit
    galaxy = await asyncio.to_thread(build_galaxy, raw, signal, k)
    cache.set(f"galaxy:{key}", galaxy)
    return galaxy


async def build(
    source: Source,
    cache: Cache,
    login: str,
    depth: int,
    max_people: int,
    signal: str,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Return the galaxy, crawling only if neither it nor the raw crawl is cached."""
    check_params(login, depth, max_people, signal)
    hit = cached_galaxy(cache, login, depth, max_people, signal)
    if hit:
        return hit
    raw = cached_raw(cache, login, depth, max_people)
    if raw is None:
        raw = await crawl(source, login, depth, max_people, progress)
        cache.set(raw_key(login, depth, max_people), raw.to_dict())
        if raw.seed.lower() != login.lower():  # pragma: no cover - logins are case-only aliases
            cache.set(raw_key(raw.seed, depth, max_people), raw.to_dict())
    if progress:
        maybe = progress({"stage": "clustering", "done": 0, "total": 1,
                          "msg": f"Clustering {len(raw.people)} people"})
        if maybe is not None:
            await maybe
    return await galaxy_from_raw(cache, raw, signal)
