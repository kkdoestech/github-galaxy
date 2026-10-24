"""GitHub access: REST for follow lists (fast to page), GraphQL for profiles (batched).

Both share one client that retries, backs off on secondary rate limits, and tracks how much
of the hourly budget a build used. Results are cached per user, so overlapping galaxies
reuse what earlier builds fetched.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from .cache import DAY, Cache
from .models import Person, Repo

API = "https://api.github.com"
RATE = "rateLimit { cost remaining resetAt }"
PROFILE_BATCH = 10  # users per GraphQL query
CONTRIB_BATCH = 3  # repositoriesContributedTo is slow on GitHub's side; keep these small
CONTRIB_TIMEOUT = 15.0  # contributions are a bonus; skip people whose query is this slow
PAGE = 100

OnProgress = Callable[[int, int], Awaitable[None] | None]


async def _notify(callback: OnProgress | None, done: int, total: int) -> None:
    if callback is None:
        return
    maybe = callback(done, total)
    if maybe is not None:
        await maybe


class GitHubError(Exception):
    def __init__(self, code: str, message: str, reset_at: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reset_at = reset_at


class TransientError(Exception):
    """The query timed out or GitHub returned 5xx. A smaller batch usually works."""


@dataclass
class Edges:
    following: list[str] = field(default_factory=list)
    followers: list[str] = field(default_factory=list)
    following_total: int = 0
    followers_total: int = 0


class Source(Protocol):
    """What the crawler needs. GitHubSource talks to GitHub; tests use a fake."""

    points: int
    queries: int

    async def owner(self, login: str) -> tuple[str, str] | None: ...

    async def edges(
        self,
        logins: list[str],
        following_cap: int,
        followers_cap: int,
        followers_max_total: int,
        on_progress: OnProgress | None = None,
    ) -> dict[str, Edges]: ...

    async def profiles(
        self,
        logins: list[str],
        with_contrib: set[str] = frozenset(),
        on_progress: OnProgress | None = None,
    ) -> dict[str, Person | None]: ...


def _lit(s: str) -> str:
    """A GraphQL string literal (JSON string syntax is valid GraphQL)."""
    return json.dumps(s)


def _last_page(link: str | None) -> int:
    """Page count from a REST `Link` header; 1 when there is no next page."""
    match = re.search(r'[?&]page=(\d+)[^>]*>;\s*rel="last"', link or "")
    return int(match.group(1)) if match else 1


class GitHubClient:
    def __init__(
        self,
        token: str | None,
        http: httpx.AsyncClient | None = None,
        concurrency: int = 8,
        rest_concurrency: int = 10,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.token = token
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self.gql_sem = asyncio.Semaphore(concurrency)
        self.rest_sem = asyncio.Semaphore(rest_concurrency)
        self.sleep = sleep
        self.points = 0  # GraphQL cost
        self.rest_calls = 0
        self.queries = 0
        self.remaining: int | None = None
        self.reset_at: str | None = None

    async def _send(
        self, sem: asyncio.Semaphore, method: str, url: str, timeout: float | None, **kwargs: Any
    ) -> httpx.Response:
        if not self.token:
            raise GitHubError("NO_TOKEN", "No GitHub token is set. Add GITHUB_TOKEN to .env.")
        headers = {
            "Authorization": f"bearer {self.token}",
            "User-Agent": "github-galaxy",
            "Accept": "application/vnd.github+json",
        }
        extra = {"timeout": timeout} if timeout else {}
        for attempt in range(5):
            try:
                async with sem:
                    resp = await self.http.request(method, url, headers=headers, **extra, **kwargs)
            except httpx.TimeoutException as exc:
                raise TransientError("GitHub timed out") from exc
            except httpx.TransportError as exc:
                if attempt == 4:
                    raise GitHubError("UPSTREAM", f"Could not reach GitHub: {exc}") from exc
                await self.sleep(2**attempt)
                continue

            if resp.status_code in (502, 503, 504):
                if attempt >= 1:
                    raise TransientError(f"GitHub returned {resp.status_code}")
                await self.sleep(1)
                continue
            if resp.status_code == 401:
                raise GitHubError("NO_TOKEN", "GitHub rejected the token. Check GITHUB_TOKEN.")
            if resp.status_code in (403, 429):
                if resp.headers.get("x-ratelimit-remaining") == "0":
                    reset = resp.headers.get("x-ratelimit-reset")
                    reset_at = (
                        datetime.fromtimestamp(int(reset), UTC).isoformat() if reset else None
                    )
                    raise GitHubError("RATE_LIMITED", "GitHub rate limit reached.", reset_at)
                # secondary rate limit: back off and retry
                wait = float(resp.headers.get("retry-after") or 20 * (attempt + 1))
                await self.sleep(min(wait, 90))
                continue
            if resp.status_code not in (200, 404):
                raise GitHubError("UPSTREAM", f"GitHub returned HTTP {resp.status_code}.")
            self.queries += 1
            return resp
        raise GitHubError("UPSTREAM", "GitHub kept refusing the request. Try again later.")

    async def run(self, query: str, timeout: float | None = None) -> dict[str, Any]:
        """Run a GraphQL query. Partial data (some aliases null) is returned as is."""
        resp = await self._send(
            self.gql_sem, "POST", f"{API}/graphql", timeout, json={"query": query}
        )
        try:
            body = resp.json()
        except ValueError as exc:  # GitHub sometimes answers a slow query with an empty body
            raise TransientError("GitHub sent an unreadable response") from exc
        data = body.get("data") or {}
        errors = body.get("errors") or []
        for err in errors:
            if err.get("type") == "RATE_LIMITED":
                raise GitHubError("RATE_LIMITED", "GitHub rate limit reached.", self.reset_at)
        rate = data.get("rateLimit")
        if rate:
            self.points += rate.get("cost", 0)
            self.remaining = rate.get("remaining")
            self.reset_at = rate.get("resetAt")
        if not data and errors:
            raise GitHubError("UPSTREAM", errors[0].get("message", "GitHub query failed."))
        return data

    async def rest(self, path: str, **params: Any) -> httpx.Response | None:
        """GET a REST endpoint. None when it doesn't exist (404)."""
        resp = await self._send(self.rest_sem, "GET", f"{API}{path}", None, params=params)
        self.rest_calls += 1
        return None if resp.status_code == 404 else resp

    async def rate_limit(self) -> dict[str, Any]:
        data = await self.run(f"query {{ {RATE} }}")
        return data["rateLimit"]

    async def aclose(self) -> None:
        await self.http.aclose()


PROFILE_FIELDS = """
login name avatarUrl(size: 96) bio
followers { totalCount } following { totalCount }
repositories(first: 5, ownerAffiliations: [OWNER], isFork: false, privacy: PUBLIC,
             orderBy: {field: STARGAZERS, direction: DESC}) {
  nodes { nameWithOwner stargazerCount primaryLanguage { name }
          repositoryTopics(first: 5) { nodes { topic { name } } } }
}
"""

CONTRIB_FIELDS = """
repositoriesContributedTo(first: 15, privacy: PUBLIC, includeUserRepositories: false,
                          contributionTypes: [COMMIT, PULL_REQUEST, PULL_REQUEST_REVIEW]) {
  nodes { nameWithOwner stargazerCount primaryLanguage { name } }
}
"""


def _repo(r: dict[str, Any]) -> Repo:
    return Repo(
        name=r["nameWithOwner"],
        stars=r.get("stargazerCount") or 0,
        lang=(r.get("primaryLanguage") or {}).get("name"),
        topics=[t["topic"]["name"] for t in (r.get("repositoryTopics") or {}).get("nodes", [])],
    )


def parse_profile(u: dict[str, Any]) -> Person:
    return Person(
        login=u["login"],
        name=u.get("name") or None,
        avatar=u.get("avatarUrl"),
        bio=(u.get("bio") or "").strip()[:200] or None,
        followers=(u.get("followers") or {}).get("totalCount", 0),
        following=(u.get("following") or {}).get("totalCount", 0),
        repos=[_repo(r) for r in (u.get("repositories") or {}).get("nodes", []) if r],
    )


def parse_contrib(u: dict[str, Any]) -> list[Repo]:
    return [_repo(r) for r in (u.get("repositoriesContributedTo") or {}).get("nodes", []) if r]


SKIPPED = object()  # an optional fetch that gave up; not cached, so a later build retries


async def _halving(
    items: list, run: Callable[[list], Awaitable[dict]], optional: bool = False
) -> dict:
    """Run a batch; if GitHub chokes on it, split it in half and try again."""
    try:
        return await run(items)
    except TransientError as exc:
        if len(items) == 1:
            if optional:
                return {items[0]: SKIPPED}
            raise GitHubError("UPSTREAM", "GitHub timed out on a single user. Try again.") from exc
        mid = len(items) // 2
        left, right = await asyncio.gather(
            _halving(items[:mid], run, optional), _halving(items[mid:], run, optional)
        )
        return {**left, **right}


class GitHubSource:
    def __init__(self, client: GitHubClient, cache: Cache | None = None, max_age: float = DAY):
        self.client = client
        self.cache = cache
        self.max_age = max_age

    @property
    def points(self) -> int:
        """Budget used: GraphQL points plus REST requests."""
        return self.client.points + self.client.rest_calls

    @property
    def queries(self) -> int:
        return self.client.queries

    def _cached(self, key: str) -> Any | None:
        return self.cache.get(key, self.max_age) if self.cache else None

    async def owner(self, login: str) -> tuple[str, str] | None:
        data = await self.client.run(
            f"query {{ repositoryOwner(login: {_lit(login)}) {{ __typename login }} {RATE} }}"
        )
        owner = data.get("repositoryOwner")
        return (owner["login"], owner["__typename"]) if owner else None

    async def _list(self, login: str, direction: str, cap: int, max_total: int):
        """One follow list. Returns (logins, approximate total)."""
        first = await self.client.rest(f"/users/{login}/{direction}", per_page=PAGE, page=1)
        if first is None:
            return [], 0
        names = [u["login"] for u in first.json()]
        pages = _last_page(first.headers.get("link"))
        total = len(names) if pages == 1 else pages * PAGE  # upper bound, good enough
        if total > max_total:
            return [], total
        wanted = min(pages, max(1, math.ceil(cap / PAGE)))
        rest = await asyncio.gather(
            *(self.client.rest(f"/users/{login}/{direction}", per_page=PAGE, page=p)
              for p in range(2, wanted + 1))
        )
        for resp in rest:
            if resp is not None:
                names += [u["login"] for u in resp.json()]
        return names[:cap], total

    async def edges(
        self,
        logins: list[str],
        following_cap: int,
        followers_cap: int,
        followers_max_total: int,
        on_progress: OnProgress | None = None,
    ) -> dict[str, Edges]:
        result: dict[str, Edges] = {}
        tag = f"{following_cap}:{followers_cap}:{followers_max_total}"
        todo = []
        for login in logins:
            hit = self._cached(f"edges:{login.lower()}:{tag}")
            if hit is not None:
                result[login] = Edges(**hit)
            else:
                todo.append(login)

        async def one(login: str) -> tuple[str, Edges]:
            (following, f_total), (followers, r_total) = await asyncio.gather(
                self._list(login, "following", following_cap, 10**9),
                self._list(login, "followers", followers_cap, followers_max_total),
            )
            return login, Edges(following, followers, f_total, r_total)

        tasks = [asyncio.ensure_future(one(login)) for login in todo]
        try:
            for next_done in asyncio.as_completed(tasks):
                login, e = await next_done
                result[login] = e
                if self.cache:
                    self.cache.set(f"edges:{login.lower()}:{tag}", e.__dict__)
                await _notify(on_progress, len(result), len(logins))
        finally:
            for task in tasks:
                task.cancel()
        return result

    async def _user_batch(self, logins: list[str], fields: str, timeout: float | None) -> dict:
        parts = [f"u{i}: user(login: {_lit(name)}) {{ {fields} }}" for i, name in enumerate(logins)]
        data = await self.client.run("query { " + " ".join(parts) + f" {RATE} }}", timeout)
        return {login: data.get(f"u{i}") for i, login in enumerate(logins)}

    async def _fetch(
        self,
        logins: list[str],
        prefix: str,
        fields: str,
        batch: int,
        parse: Callable,
        on_progress: OnProgress | None = None,
        optional: bool = False,
    ) -> dict[str, Any]:
        """Cached per-user fetch. Missing users are cached as {} and returned as None."""
        result: dict[str, Any] = {}
        todo = []
        for login in logins:
            hit = self._cached(f"{prefix}:{login.lower()}")
            if hit is not None:
                result[login] = parse(hit) if hit else None
            else:
                todo.append(login)

        timeout = CONTRIB_TIMEOUT if optional else None

        async def run(items: list[str]) -> dict:
            return await self._user_batch(items, fields, timeout)

        batches = [todo[i : i + batch] for i in range(0, len(todo), batch)]
        tasks = [asyncio.ensure_future(_halving(b, run, optional)) for b in batches]
        try:
            for next_done in asyncio.as_completed(tasks):
                for login, u in (await next_done).items():
                    if u is SKIPPED:
                        result[login] = None
                        continue
                    result[login] = parse(u) if u else None
                    if self.cache:
                        self.cache.set(f"{prefix}:{login.lower()}", u or {})
                await _notify(on_progress, len(result), len(logins))
        finally:
            for task in tasks:
                task.cancel()
        return result

    async def profiles(
        self,
        logins: list[str],
        with_contrib: set[str] = frozenset(),
        on_progress: OnProgress | None = None,
    ) -> dict[str, Person | None]:
        """Profiles and owned repos for everyone; recent contributions for `with_contrib`."""
        contrib_logins = [login for login in logins if login in with_contrib]
        counts = [0, 0]

        def tracker(slot: int) -> OnProgress:
            async def update(done: int, _total: int) -> None:
                counts[slot] = done
                await _notify(on_progress, sum(counts), len(logins) + len(contrib_logins))

            return update

        people, contribs = await asyncio.gather(
            self._fetch(logins, "profile", PROFILE_FIELDS, PROFILE_BATCH, parse_profile,
                        tracker(0)),
            self._fetch(contrib_logins, "contrib", CONTRIB_FIELDS, CONTRIB_BATCH, parse_contrib,
                        tracker(1), optional=True),
        )
        for login, repos in contribs.items():
            if people.get(login) is not None and repos:
                people[login].contributed = repos
        return people
