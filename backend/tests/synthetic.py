"""Synthetic follow networks with planted groups, for tests and offline demos."""

from __future__ import annotations

import numpy as np

from galaxy.models import Person, RawGraph, Repo

LANGS = ["Rust", "Go", "TypeScript", "Python", "C", "Kotlin", "Ruby", "Haskell"]


def sbm_raw(
    blocks: int = 4,
    size: int = 60,
    p_in: float = 0.25,
    p_out: float = 0.01,
    seed: int = 0,
) -> tuple[RawGraph, np.ndarray]:
    """Stochastic block model as a directed follow graph. Returns (raw graph, true groups)."""
    rng = np.random.default_rng(seed)
    n = blocks * size
    truth = np.repeat(np.arange(blocks), size)
    logins = [f"dev{i:04d}" for i in range(n)]
    people = {}
    for i, login in enumerate(logins):
        lang = LANGS[truth[i] % len(LANGS)]
        people[login] = Person(
            login=login,
            name=f"Dev {i}",
            followers=int(rng.integers(0, 5000)),
            hop=0 if i == 0 else 1 + int(i % 2),
            repos=[Repo(name=f"{login}/tool", stars=int(rng.integers(0, 900)), lang=lang,
                        topics=[f"topic-{truth[i]}"])],
        )
    follows = set()
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            p = p_in if truth[i] == truth[j] else p_out
            if rng.random() < p:
                follows.add((logins[i], logins[j]))
    raw = RawGraph(seed=logins[0], depth=2, max_people=n, people=people, follows=follows,
                   built_at="2026-01-01T00:00:00Z")
    return raw, truth
