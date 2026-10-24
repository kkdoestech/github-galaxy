import json

import pytest
from fastapi.testclient import TestClient

from galaxy.api import create_app
from galaxy.cache import Cache

from .fakes import FakeSource
from .synthetic import sbm_raw


def fake_source():
    raw, _ = sbm_raw(blocks=3, size=40, p_in=0.3, p_out=0.01, seed=2)
    following: dict[str, list[str]] = {login: [] for login in raw.people}
    for a, b in raw.follows:
        following[a].append(b)
    return FakeSource(following), raw.seed


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("GALAXY_NO_GH_CLI", "1")
    src, seed = fake_source()
    cache = Cache()
    app = create_app(source=src, cache=cache, serve_frontend=False)
    with TestClient(app) as client:
        yield client, src, seed


def read_events(resp):
    events = []
    for block in resp.text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if not ln.startswith(":")]
        if not lines:
            continue
        name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((name, data))
    return events


def test_stream_emits_progress_then_result(setup):
    client, src, seed = setup
    resp = client.get("/api/galaxy/stream", params={"u": seed, "d": 2, "n": 500})
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = read_events(resp)
    names = [e[0] for e in events]
    assert names[-1] == "result"
    assert "progress" in names
    galaxy = events[-1][1]
    assert galaxy["seed"] == seed and galaxy["stats"]["people"] > 50
    assert galaxy["spectral"]["k"] == len(galaxy["clusters"])

    # second request comes from the cache without touching GitHub
    calls_before = src.queries
    again = read_events(client.get("/api/galaxy/stream", params={"u": seed, "d": 2, "n": 500}))
    assert [e[0] for e in again] == ["result"]
    assert src.queries == calls_before


def test_recluster_changes_k_without_crawling(setup):
    client, src, seed = setup
    galaxy = read_events(client.get("/api/galaxy/stream", params={"u": seed, "n": 500}))[-1][1]
    calls_before = src.queries
    resp = client.post("/api/recluster", json={"key": galaxy["key"], "k": 5, "s": "follow"})
    assert resp.status_code == 200
    out = resp.json()
    assert out["spectral"]["k"] == 5 and len(out["clusters"]) == 5
    assert out["params"]["signal"] == "follow"
    assert src.queries == calls_before


@pytest.mark.parametrize(
    "params, code",
    [
        ({"u": "-bad-"}, "BAD_INPUT"),
        ({"u": "ok", "d": 4}, "BAD_INPUT"),
        ({"u": "ok", "n": 50}, "BAD_INPUT"),
        ({"u": "ok", "s": "stars"}, "BAD_INPUT"),
        ({"u": "nobody-here"}, "NOT_FOUND"),
    ],
)
def test_stream_errors(setup, params, code):
    client, _, _ = setup
    events = read_events(client.get("/api/galaxy/stream", params=params))
    assert events[-1][0] == "error" and events[-1][1]["code"] == code
    assert events[-1][1]["msg"]


def test_recluster_errors(setup):
    client, _, _ = setup
    assert client.post("/api/recluster", json={"key": "nope"}).status_code == 400
    assert client.post("/api/recluster", json={"key": "x:2:800:collab", "k": 50}).status_code == 400
    assert client.post("/api/recluster", json={"key": "x:2:800:collab"}).status_code == 404


def test_health(setup):
    client, _, _ = setup
    body = client.get("/api/health").json()
    assert body["ok"] is True
