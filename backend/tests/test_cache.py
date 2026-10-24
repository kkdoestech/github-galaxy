import time

from galaxy.cache import Cache


def test_roundtrip_and_max_age(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    cache.set("a", {"x": [1, 2]})
    assert cache.get("a") == {"x": [1, 2]}
    assert cache.get("missing") is None
    time.sleep(0.01)
    assert cache.get("a", max_age=0.001) is None


def test_version_isolates_old_entries(tmp_path):
    path = tmp_path / "c.sqlite3"
    old = Cache(path, version="v0")
    old.set("profile:x", {"old": True})
    old.close()
    assert Cache(path, version="v1").get("profile:x") is None
