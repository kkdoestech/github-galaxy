import asyncio
import json
import re

import httpx
import pytest

from galaxy.cache import Cache
from galaxy.github import GitHubClient, GitHubError, GitHubSource, _last_page

RATE = {"cost": 1, "remaining": 4999, "resetAt": "2026-01-01T01:00:00Z"}


async def no_sleep(_):
    return None


def make_source(handler, cache=None):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GitHubSource(GitHubClient("t0ken", http=http, sleep=no_sleep), cache)


def ok(data):
    return httpx.Response(200, json={"data": {**data, "rateLimit": RATE}})


def users(*names):
    return [{"login": n} for n in names]


def link(path, last):
    return f'<https://api.github.com{path}?per_page=100&page={last}>; rel="last"'


def test_last_page():
    assert _last_page(None) == 1
    header = ('<https://api.github.com/user/1/following?per_page=100&page=2>; rel="next", '
              '<https://api.github.com/user/1/following?per_page=100&page=7>; rel="last"')
    assert _last_page(header) == 7


def test_owner_lookup_and_points():
    def handler(request):
        assert request.headers["authorization"] == "bearer t0ken"
        return ok({"repositoryOwner": {"__typename": "User", "login": "Octocat"}})

    src = make_source(handler)
    assert asyncio.run(src.owner("octocat")) == ("Octocat", "User")
    assert src.points == 1 and src.queries == 1


def rest_network(pages):
    """pages: {(login, direction): [[names on page 1], [page 2], ...]}"""
    calls = []

    def handler(request):
        m = re.match(r"/users/([^/]+)/(following|followers)", request.url.path)
        login, direction = m.groups()
        page = int(request.url.params.get("page", 1))
        calls.append((login, direction, page))
        book = pages.get((login, direction))
        if book is None:
            return httpx.Response(404)
        headers = {"link": link(request.url.path, len(book))} if len(book) > 1 else {}
        return httpx.Response(200, json=users(*book[page - 1]), headers=headers)

    return handler, calls


def test_edges_fetch_all_pages_up_to_cap():
    handler, calls = rest_network({
        ("me", "following"): [[f"f{i}" for i in range(100)], [f"f{i}" for i in range(100, 150)]],
        ("me", "followers"): [["g1"]],
    })
    cache = Cache()
    src = make_source(handler, cache)
    e = asyncio.run(src.edges(["me"], 300, 500, 500))["me"]
    assert len(e.following) == 150 and e.followers == ["g1"]
    assert e.following_total == 200  # two pages: upper bound
    assert len(calls) == 3
    again = asyncio.run(src.edges(["me"], 300, 500, 500))["me"]
    assert again.following == e.following and len(calls) == 3  # cached


def test_cap_limits_pages():
    handler, calls = rest_network({
        ("me", "following"): [["a"] * 100, ["b"] * 100, ["c"] * 100],
        ("me", "followers"): [[]],
    })
    e = asyncio.run(make_source(handler).edges(["me"], 100, 100, 100))["me"]
    assert len(e.following) == 100 and e.following_total == 300
    assert sorted(c[2] for c in calls if c[1] == "following") == [1]


def test_famous_followers_dropped():
    handler, calls = rest_network({
        ("star", "following"): [["x"]],
        ("star", "followers"): [["fan"] * 100] * 900,
    })
    e = asyncio.run(make_source(handler).edges(["star"], 200, 300, 300))["star"]
    assert e.followers == [] and e.followers_total == 90000
    assert e.following == ["x"]
    assert len([c for c in calls if c[1] == "followers"]) == 1  # no more pages fetched


def test_missing_user_has_no_edges():
    handler, _ = rest_network({})
    e = asyncio.run(make_source(handler).edges(["ghost"], 100, 100, 100))["ghost"]
    assert e.following == [] and e.followers == []


def test_edges_progress():
    handler, _ = rest_network({(u, d): [[]] for u in "abc" for d in ("following", "followers")})
    seen = []
    asyncio.run(make_source(handler).edges(list("abc"), 100, 100, 100,
                                           lambda done, total: seen.append((done, total))))
    assert seen[-1] == (3, 3)


def test_profiles_parse_and_cache_missing_users():
    seen = []

    def handler(request):
        query = json.loads(request.content)["query"]
        assert "privacy: PUBLIC" in query
        if "repositoriesContributedTo" in query:
            seen.append("contrib")
            assert '"ghost"' not in query  # only asked for people in with_contrib
            return ok({"u0": {"repositoriesContributedTo": {"nodes": [
                {"nameWithOwner": "o/y", "stargazerCount": 1, "primaryLanguage": None}]}}})
        seen.append("profile")
        return ok({
            "u0": {"login": "Ann", "name": "Ann", "avatarUrl": "a.png", "bio": " hi ",
                   "followers": {"totalCount": 5}, "following": {"totalCount": 2},
                   "repositories": {"nodes": [{"nameWithOwner": "Ann/x", "stargazerCount": 9,
                                               "primaryLanguage": {"name": "Rust"},
                                               "repositoryTopics": {"nodes": [
                                                   {"topic": {"name": "wasm"}}]}}]}},
            "u1": None,
        })

    cache = Cache()
    src = make_source(handler, cache)
    out = asyncio.run(src.profiles(["ann", "ghost"], with_contrib={"ann"}))
    ann = out["ann"]
    assert ann.login == "Ann" and ann.bio == "hi" and ann.followers == 5
    assert ann.repos[0].topics == ["wasm"] and ann.repos[0].lang == "Rust"
    assert ann.contributed[0].name == "o/y" and ann.contributed[0].lang is None
    assert out["ghost"] is None
    assert sorted(seen) == ["contrib", "profile"]
    out2 = asyncio.run(src.profiles(["ann", "ghost"], with_contrib={"ann"}))
    assert out2["ghost"] is None and out2["ann"].contributed[0].name == "o/y"
    assert len(seen) == 2  # all from cache


def profile_handler(fail_contrib_for=()):
    def handler(request):
        query = json.loads(request.content)["query"]
        aliases = re.findall(r"(u\d+): user\(login: \"([^\"]+)\"\)", query)
        if "repositoriesContributedTo" in query:
            if any(login in fail_contrib_for for _, login in aliases):
                raise httpx.ReadTimeout("slow")
            return ok({a: {"repositoriesContributedTo": {"nodes": [
                {"nameWithOwner": f"{login}/c"}]}} for a, login in aliases})
        if len(aliases) > 5:
            return httpx.Response(502)
        return ok({a: {"login": login} for a, login in aliases})

    return handler


def test_batch_halves_on_502():
    src = make_source(profile_handler())
    out = asyncio.run(src.profiles([f"p{i}" for i in range(20)]))
    assert len(out) == 20 and all(p is not None for p in out.values())


def test_slow_contributions_are_skipped_not_fatal():
    cache = Cache()
    src = make_source(profile_handler(fail_contrib_for={"p1"}), cache)
    out = asyncio.run(src.profiles(["p0", "p1", "p2"], with_contrib={"p0", "p1", "p2"}))
    assert out["p1"].contributed == []
    assert out["p0"].contributed[0].name == "p0/c"
    assert cache.get("contrib:p1") is None  # retried next time


def test_unreadable_body_is_retried_smaller():
    def handler(request):
        query = json.loads(request.content)["query"]
        aliases = re.findall(r"(u\d+): user\(login: \"([^\"]+)\"\)", query)
        if len(aliases) > 2:
            return httpx.Response(200, content=b"")
        return ok({a: {"login": login} for a, login in aliases})

    out = asyncio.run(make_source(handler).profiles([f"p{i}" for i in range(8)]))
    assert all(out[f"p{i}"].login == f"p{i}" for i in range(8))


@pytest.mark.parametrize(
    "response, code",
    [
        (httpx.Response(401), "NO_TOKEN"),
        (httpx.Response(403, headers={"x-ratelimit-remaining": "0",
                                      "x-ratelimit-reset": "1767225600"}), "RATE_LIMITED"),
        (httpx.Response(200, json={"errors": [{"type": "RATE_LIMITED", "message": "x"}]}),
         "RATE_LIMITED"),
        (httpx.Response(200, json={"errors": [{"message": "Something broke"}]}), "UPSTREAM"),
        (httpx.Response(500), "UPSTREAM"),
    ],
)
def test_error_mapping(response, code):
    src = make_source(lambda request: response)
    with pytest.raises(GitHubError) as e:
        asyncio.run(src.owner("x"))
    assert e.value.code == code


def test_no_token():
    src = GitHubSource(GitHubClient(None))
    with pytest.raises(GitHubError) as e:
        asyncio.run(src.owner("x"))
    assert e.value.code == "NO_TOKEN"


def test_secondary_limit_retries():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(403, headers={"retry-after": "1"})
        return ok({"repositoryOwner": None})

    src = make_source(handler)
    assert asyncio.run(src.owner("x")) is None
    assert len(calls) == 2
