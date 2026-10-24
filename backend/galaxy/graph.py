"""Turn a crawled follow network into a weighted, undirected sparse graph."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from .models import RawGraph

FOLLOW_MUTUAL = 1.0
FOLLOW_ONE_WAY = 0.5
COLLAB_CAP = 2.0
MAX_REPO_MEMBERS = 50

SIGNALS = ("collab", "follow")


@dataclass
class WeightedGraph:
    ids: list[str]
    W: sparse.csr_matrix  # symmetric, zero diagonal
    links: list[dict]  # one per undirected edge, source -> target in follow direction

    def index_of(self, login: str) -> int:
        return self.ids.index(login)


def repo_members(raw: RawGraph) -> dict[str, set[str]]:
    """Repo name -> people in the graph who own it or recently contributed to it."""
    members: dict[str, set[str]] = defaultdict(set)
    for login, person in raw.people.items():
        for repo in person.repos:
            members[repo.name].add(login)
        for repo in person.contributed:
            members[repo.name].add(login)
    return members


def collab_weights(raw: RawGraph) -> dict[tuple[str, str], float]:
    """Pair weight = sum over shared repos of 1/log2(1 + members), capped.

    Small repos say more about who works together than huge ones, the same idea as IDF.
    """
    pair_w: dict[tuple[str, str], float] = defaultdict(float)
    for members in repo_members(raw).values():
        size = len(members)
        if size < 2 or size > MAX_REPO_MEMBERS:
            continue
        w = 1.0 / math.log2(1 + size)
        ordered = sorted(members)
        for i in range(size):
            for j in range(i + 1, size):
                pair_w[(ordered[i], ordered[j])] += w
    return {pair: min(w, COLLAB_CAP) for pair, w in pair_w.items()}


def build_graph(raw: RawGraph, signal: str = "collab") -> WeightedGraph:
    if signal not in SIGNALS:
        raise ValueError(f"signal must be one of {SIGNALS}")
    ids = sorted(raw.people)
    index = {login: i for i, login in enumerate(ids)}
    follows = {(a, b) for a, b in raw.follows if a in index and b in index and a != b}

    # sorted pair -> [weight, kind, source, target]
    edges: dict[tuple[str, str], list] = {}
    for a, b in follows:
        pair = (a, b) if a < b else (b, a)
        if pair in edges:
            continue
        if (b, a) in follows:
            edges[pair] = [FOLLOW_MUTUAL, "mutual", pair[0], pair[1]]
        else:
            edges[pair] = [FOLLOW_ONE_WAY, "follow", a, b]

    if signal == "collab":
        for pair, w in collab_weights(raw).items():
            if pair in edges:
                edges[pair][0] += w
            else:
                edges[pair] = [w, "collab", pair[0], pair[1]]

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    links: list[dict] = []
    for (a, b), (w, kind, source, target) in sorted(edges.items()):
        i, j = index[a], index[b]
        rows += [i, j]
        cols += [j, i]
        vals += [w, w]
        links.append({"source": source, "target": target, "w": round(w, 3), "kind": kind})

    n = len(ids)
    W = sparse.csr_matrix((vals, (rows, cols)), shape=(n, n), dtype=np.float64)
    return WeightedGraph(ids, W, links)


def component_of(g: WeightedGraph, login: str) -> WeightedGraph:
    """Keep only the connected component that contains `login`."""
    if not g.ids:
        return g
    _, comp = connected_components(g.W, directed=False)
    target = comp[g.index_of(login)] if login in g.ids else np.bincount(comp).argmax()
    keep = np.flatnonzero(comp == target)
    if len(keep) == len(g.ids):
        return g
    kept_ids = [g.ids[i] for i in keep]
    kept = set(kept_ids)
    W = g.W[keep][:, keep].tocsr()
    links = [link for link in g.links if link["source"] in kept and link["target"] in kept]
    return WeightedGraph(kept_ids, W, links)
