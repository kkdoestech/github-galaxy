"""Raw crawl -> weighted graph -> clusters -> layout -> galaxy JSON."""

from __future__ import annotations

from typing import Any

from .graph import build_graph, component_of
from .labels import describe_clusters, person_langs
from .layout import layout
from .models import RawGraph
from .spectral import cluster

GALAXY_VERSION = 1


def galaxy_key(login: str, depth: int, max_people: int, signal: str) -> str:
    return f"{login.lower()}:{depth}:{max_people}:{signal}"


def build_galaxy(raw: RawGraph, signal: str = "collab", k: int | None = None) -> dict[str, Any]:
    g = component_of(build_graph(raw, signal), raw.seed)
    result = cluster(g.W, k=k)
    focus = g.index_of(raw.seed) if raw.seed in g.ids else None
    positions, _ = layout(g.W, result.labels, focus)
    clusters = describe_clusters(raw.people, g.ids, result.labels)

    nodes = []
    for i, login in enumerate(g.ids):
        p = raw.people[login]
        nodes.append(
            {
                "id": login,
                "name": p.name,
                "avatar": p.avatar,
                "bio": p.bio,
                "followers": p.followers,
                "hop": p.hop,
                "cluster": int(result.labels[i]),
                "pos": [round(float(v), 1) for v in positions[i]],
                "langs": person_langs(p)[:3],
                "repos": [
                    {"name": r.name, "stars": r.stars, "lang": r.lang} for r in p.repos[:3]
                ],
            }
        )

    return {
        "version": GALAXY_VERSION,
        "key": galaxy_key(raw.seed, raw.depth, raw.max_people, signal),
        "seed": raw.seed,
        "params": {"depth": raw.depth, "max": raw.max_people, "signal": signal, "k": k},
        "built_at": raw.built_at,
        "stats": {
            "people": len(nodes),
            "links": len(g.links),
            "api_points": raw.api_points,
            "dropped": len(raw.people) - len(nodes),
        },
        "nodes": nodes,
        "links": g.links,
        "clusters": clusters,
        "spectral": {
            "k": result.k,
            "k_auto": result.k_auto,
            "eigenvalues": result.eigenvalues,
            "modularity": result.modularity,
        },
    }
