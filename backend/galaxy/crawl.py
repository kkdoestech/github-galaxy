"""Budgeted breadth-first crawl of the follow network around one user.

Rules (see README, "How the crawl works"):
- Hop 1 is everyone the seed follows or is followed by: mutuals first, then following, then
  followers. Their own lists are fetched too, so we learn the links between them.
- `following` is always fetched (people choose whom they follow). `followers` only when the
  account has few of them; a famous account's followers are mostly strangers.
- Further hops only admit people linked to at least two people already in the galaxy. That
  keeps real groups and drops the long tail of one-off connections.
- Accounts that follow thousands of people (follow-for-follow farms) are left out: they link
  to everyone, which would blur every group.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .github import Edges, GitHubError, Source
from .models import RawGraph

SEED_FOLLOWING_CAP = 500
SEED_FOLLOWERS_CAP = 500
SEED_FOLLOWERS_MAX_TOTAL = 5000
FOLLOWING_CAP = 200
FOLLOWERS_CAP = 300
FOLLOWERS_MAX_TOTAL = 300
EXPAND_HOP1 = 150
EXPAND_HOP2 = 100
MIN_LINKS = 2
MASS_FOLLOW = 5000  # following more than this: a follow-for-follow account, not a peer

Progress = Callable[[dict[str, Any]], Awaitable[None] | None]


async def _report(progress: Progress | None, **event: Any) -> None:
    if progress is None:
        return
    maybe = progress(event)
    if maybe is not None:
        await maybe


def _add_edges(follows: set[tuple[str, str]], login: str, e: Edges) -> None:
    for other in e.following:
        follows.add((login, other))
    for other in e.followers:
        follows.add((other, login))


def is_mass_follower(following: int, followers: int) -> bool:
    return following > MASS_FOLLOW or (following > 2000 and following > 2 * followers)


async def _expand(
    source: Source,
    logins: list[str],
    follows: set[tuple[str, str]],
    progress: Progress | None,
    label: str,
) -> set[str]:
    """Fetch the follow lists of `logins` into `follows`. Returns the mass followers found."""

    async def report(done: int, total: int) -> None:
        await _report(progress, stage="follows", done=done, total=total,
                      msg=f"Fetching follows of {label}: {done}/{total}")

    edges = await source.edges(logins, FOLLOWING_CAP, FOLLOWERS_CAP, FOLLOWERS_MAX_TOTAL, report)
    farms = set()
    for login, e in edges.items():
        if e.following_total > MASS_FOLLOW:
            farms.add(login)
        else:
            _add_edges(follows, login, e)
    return farms


def _drop(
    hop: dict[str, int], follows: set[tuple[str, str]], gone: set[str]
) -> set[tuple[str, str]]:
    for login in gone:
        if hop.get(login, 0) > 0:
            del hop[login]
    if not gone:
        return follows
    return {(a, b) for a, b in follows if a not in gone and b not in gone}


def add_frontier(
    hop: dict[str, int], follows: set[tuple[str, str]], next_hop: int, budget: int
) -> list[str]:
    """Admit outside people linked to >= MIN_LINKS galaxy members, best-connected first."""
    if budget <= 0:
        return []
    links: dict[str, set[str]] = defaultdict(set)
    for a, b in follows:
        if a in hop and b not in hop:
            links[b].add(a)
        elif b in hop and a not in hop:
            links[a].add(b)
    ranked = sorted(
        (c for c, s in links.items() if len(s) >= MIN_LINKS),
        key=lambda c: (-len(links[c]), c.lower()),
    )
    added = ranked[:budget]
    for c in added:
        hop[c] = next_hop
    return added


async def crawl(
    source: Source,
    login: str,
    depth: int = 2,
    max_people: int = 800,
    progress: Progress | None = None,
) -> RawGraph:
    await _report(progress, stage="seed", done=0, total=1, msg=f"Looking up {login}")
    owner = await source.owner(login)
    if owner is None:
        raise GitHubError("NOT_FOUND", f"There is no GitHub user named {login}.")
    seed, kind = owner
    if kind == "Organization":
        raise GitHubError("ORG_NOT_SUPPORTED", f"{seed} is an organization. Enter a person.")
    if kind != "User":
        raise GitHubError("NOT_FOUND", f"{seed} is not a regular user account.")

    seed_edges = (
        await source.edges([seed], SEED_FOLLOWING_CAP, SEED_FOLLOWERS_CAP, SEED_FOLLOWERS_MAX_TOTAL)
    )[seed]
    if not seed_edges.following and not seed_edges.followers and seed_edges.followers_total:
        # famous and follows nobody: recent followers are all we have
        seed_edges = (await source.edges([seed], 0, 300, 10**9))[seed]

    follows: set[tuple[str, str]] = set()
    _add_edges(follows, seed, seed_edges)
    followers = set(seed_edges.followers)
    mutual = [x for x in seed_edges.following if x in followers]
    ordered = list(dict.fromkeys(mutual + seed_edges.following + seed_edges.followers))
    hop1 = [x for x in ordered if x != seed][: max_people - 1]
    hop = {seed: 0}
    hop.update({x: 1 for x in hop1})

    expanded = [seed] + hop1[:EXPAND_HOP1]
    farms = await _expand(source, expanded[1:], follows, progress, f"{seed}'s network")
    follows = _drop(hop, follows, farms)

    if depth >= 2:
        hop2 = add_frontier(hop, follows, 2, max_people - len(hop))
        if depth >= 3 and hop2:
            expanded += hop2[:EXPAND_HOP2]
            farms = await _expand(source, hop2[:EXPAND_HOP2], follows, progress,
                                  "friends of friends")
            follows = _drop(hop, follows, farms)
            add_frontier(hop, follows, 3, max_people - len(hop))

    async def report(done: int, total: int) -> None:
        await _report(progress, stage="profiles", done=done, total=total,
                      msg=f"Fetching profiles and repos: {done}/{total}")

    # contributions are slow to fetch, so only for the people whose lists we fetched
    with_contrib = set(expanded) & set(hop)
    people = {}
    for name, person in (await source.profiles(list(hop), with_contrib, report)).items():
        if person is None:
            continue
        if name != seed and is_mass_follower(person.following, person.followers):
            continue
        person.hop = hop[name]
        people[person.login] = person

    if seed not in people:
        raise GitHubError("NOT_FOUND", f"Could not load the profile of {seed}.")

    return RawGraph(
        seed=seed,
        depth=depth,
        max_people=max_people,
        people=people,
        follows={(a, b) for a, b in follows if a in people and b in people},
        api_points=source.points,
        queries=source.queries,
        built_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
