import asyncio

import pytest

from galaxy import crawl as crawl_mod
from galaxy.crawl import add_frontier, crawl
from galaxy.github import GitHubError

from .fakes import FakeSource


def run(coro):
    return asyncio.run(coro)


def network():
    """seed <-> a, b, c (a ring of friends); x is a friend of a and b; y only of a."""
    return {
        "seed": ["a", "b", "c"],
        "a": ["seed", "b", "x", "y"],
        "b": ["seed", "a", "x"],
        "c": ["seed"],
        "x": ["z"],
        "y": [],
        "z": [],
    }


def test_depth_two_admits_only_well_connected_frontier():
    raw = run(crawl(FakeSource(network()), "seed", depth=2, max_people=100))
    assert raw.seed == "seed"
    assert set(raw.people) == {"seed", "a", "b", "c", "x"}  # y has one link, z is hop 3
    assert raw.people["x"].hop == 2
    assert raw.people["a"].hop == 1
    assert ("a", "b") in raw.follows and ("seed", "a") in raw.follows
    assert all(a in raw.people and b in raw.people for a, b in raw.follows)


def test_depth_one_keeps_links_between_neighbors():
    raw = run(crawl(FakeSource(network()), "seed", depth=1, max_people=100))
    assert set(raw.people) == {"seed", "a", "b", "c"}
    assert ("a", "b") in raw.follows  # learned by expanding hop 1


def test_depth_three_expands_frontier():
    net = network()
    net["c"] = ["seed", "x"]
    net["q"] = ["x", "z"]  # makes z reachable from x and q... q is outside
    net["x"] = ["z", "w"]
    net["a"].append("w")
    raw = run(crawl(FakeSource(net), "seed", depth=3, max_people=100))
    assert "x" in raw.people and raw.people["x"].hop == 2
    assert "w" in raw.people  # linked from a (hop 1) and x (hop 2)


def test_max_people_is_respected():
    following = {"seed": [f"f{i}" for i in range(50)]}
    for i in range(50):
        following[f"f{i}"] = ["seed"] + [f"g{j}" for j in range(30)]
    raw = run(crawl(FakeSource(following), "seed", depth=2, max_people=40))
    assert len(raw.people) == 40
    raw = run(crawl(FakeSource(following), "seed", depth=2, max_people=70))
    assert len(raw.people) == 70
    assert sum(1 for p in raw.people.values() if p.hop == 2) == 19


def test_mutuals_come_first_in_hop_one():
    following = {"seed": ["one_way", "mutual"], "mutual": ["seed"], "fan": ["seed"],
                 "one_way": []}
    raw = run(crawl(FakeSource(following), "seed", depth=1, max_people=2))
    assert set(raw.people) == {"seed", "mutual"}


def test_only_hop_one_is_expanded_at_depth_two(monkeypatch):
    src = FakeSource(network())
    run(crawl(src, "seed", depth=2, max_people=100))
    assert set(src.edge_calls) == {"seed", "a", "b", "c"}


def test_expand_limit(monkeypatch):
    monkeypatch.setattr(crawl_mod, "EXPAND_HOP1", 5)
    following = {"seed": [f"f{i}" for i in range(20)]}
    src = FakeSource(following)
    run(crawl(src, "seed", depth=2, max_people=100))
    assert len(src.edge_calls) == 1 + 5


def test_famous_account_followers_are_skipped(monkeypatch):
    monkeypatch.setattr(crawl_mod, "FOLLOWERS_MAX_TOTAL", 3)
    following = {"seed": ["star"], "star": ["seed"]}
    for i in range(10):
        following[f"fan{i}"] = ["star"]
    raw = run(crawl(FakeSource(following), "seed", depth=2, max_people=100))
    assert not any(login.startswith("fan") for login in raw.people)


def test_errors():
    src = FakeSource(network(), orgs={"acme"})
    with pytest.raises(GitHubError) as e:
        run(crawl(src, "nobody"))
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(GitHubError) as e:
        run(crawl(src, "acme"))
    assert e.value.code == "ORG_NOT_SUPPORTED"


def test_login_case_is_canonical():
    raw = run(crawl(FakeSource(network()), "SEED", depth=1))
    assert raw.seed == "seed"


def test_progress_events():
    events = []
    run(crawl(FakeSource(network()), "seed", depth=2, progress=events.append))
    stages = [e["stage"] for e in events]
    assert stages[0] == "seed"
    assert "follows" in stages and stages[-1] == "profiles"
    assert events[-1]["done"] == events[-1]["total"]


def test_add_frontier_ranks_by_links():
    hop = {"a": 0, "b": 1, "c": 1}
    follows = {("a", "x"), ("b", "x"), ("c", "x"), ("a", "y"), ("b", "y"), ("z", "a")}
    assert add_frontier(hop, follows, 2, 1) == ["x"]
    assert add_frontier(hop, follows, 2, 5) == ["y"]
    assert "z" not in hop


def test_contributions_only_for_expanded_people():
    src = FakeSource(network())
    raw = run(crawl(src, "seed", depth=2, max_people=100))
    assert "x" in raw.people
    assert set(src.contrib_calls) == {"seed", "a", "b", "c"}


def test_mass_followers_are_left_out():
    net = network()
    net["farm"] = ["seed", "a", "b", "c"]  # follows everyone; seed follows back
    net["seed"].append("farm")
    net["farm2"] = ["a", "b"]  # hop-2 candidate with 2 links, but follows 9000 people
    src = FakeSource(net)
    src.following_total = {"farm": 20000, "farm2": 9000}
    raw = run(crawl(src, "seed", depth=2, max_people=100))
    assert "farm" not in raw.people and "farm2" not in raw.people
    assert not any("farm" in a or "farm" in b for a, b in raw.follows)
    assert "x" in raw.people
