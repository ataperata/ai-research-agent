import json

from research_agent.cache import Cache


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_memory_cache_hit_and_miss():
    cache = Cache(None)
    assert cache.get("pages", "a") is None
    cache.set("pages", "a", {"x": 1})
    assert cache.get("pages", "a") == {"x": 1}
    assert cache.get("search", "a") is None  # namespaces are separate
    assert (cache.hits, cache.misses) == (1, 2)


def test_disk_cache_survives_new_instance(tmp_path):
    Cache(tmp_path).set("pages", "https://a.test/x", {"title": "X"})
    assert Cache(tmp_path).get("pages", "https://a.test/x") == {"title": "X"}
    assert list(tmp_path.rglob("*.json"))


def test_entries_expire(tmp_path):
    clock = Clock()
    cache = Cache(tmp_path, ttl_seconds=60, clock=clock)
    cache.set("pages", "k", "v")
    clock.now += 59
    assert cache.get("pages", "k") == "v"
    clock.now += 2
    assert cache.get("pages", "k") is None

    memory = Cache(None, ttl_seconds=60, clock=clock)
    memory.set("pages", "k", "v")
    clock.now += 61
    assert memory.get("pages", "k") is None


def test_corrupt_or_mismatched_files_are_misses(tmp_path):
    cache = Cache(tmp_path)
    cache.set("pages", "k", "v")
    path = next(tmp_path.rglob("*.json"))
    path.write_text("{not json")
    assert cache.get("pages", "k") is None
    path.write_text(json.dumps({"key": "other", "stored_at": 1e18, "value": "v"}))
    assert cache.get("pages", "k") is None
