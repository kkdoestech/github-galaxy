"""Name each cluster after the languages and topics that set it apart."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .models import Person

# Ayu's six hue families (blue, orange, teal, purple, green, red), stepped into the
# lightness band that reads on the dark background and ordered so neighbors separate
# best, including for color-blind viewers (checked with a palette validator). Clusters
# 7-18 reuse the hues one step lighter, then darker; cluster numbers and labels are always
# shown next to the color, so it is never the only cue.
PALETTE = [
    "#2C9DD7", "#DD7015", "#26A988", "#A67BD1", "#79A305", "#E2646C",
    "#71C9FE", "#FFA56C", "#5FD7B4", "#D2A8FE", "#A2D142", "#FF9FA1",
    "#0771A1", "#A24E01", "#087B61", "#7C52A3", "#567504", "#B13844",
]


def cluster_color(c: int) -> str:
    return PALETTE[c % len(PALETTE)]


def person_langs(p: Person) -> list[str]:
    """Languages by how often they appear in the person's own and contributed repos."""
    counts = Counter(r.lang for r in p.repos + p.contributed if r.lang)
    return [lang for lang, _ in counts.most_common()]


def person_terms(p: Person, display: dict[str, str]) -> set[str]:
    """Lowercased languages and topics. `display` collects how to print each one."""
    terms = set()
    for lang in person_langs(p)[:3]:
        terms.add(lang.lower())
        display[lang.lower()] = lang  # "TypeScript", not the topic "typescript"
    for repo in p.repos:
        for topic in repo.topics:
            terms.add(topic.lower())
            display.setdefault(topic.lower(), topic)
    return terms


def describe_clusters(
    people: dict[str, Person], ids: list[str], labels: np.ndarray, top_n: int = 3
) -> list[dict]:
    k = int(labels.max()) + 1 if len(labels) else 0
    n = len(ids)
    display: dict[str, str] = {}
    terms = [person_terms(people[i], display) for i in ids]
    doc_freq = Counter(t for ts in terms for t in ts)

    out = []
    for c in range(k):
        members = [i for i in range(n) if labels[i] == c]
        size = len(members)
        term_count = Counter(t for i in members for t in terms[i])
        min_support = max(2, math.ceil(size * 0.08))

        def score(t: str, count: int, size: int = size) -> float:
            # how over-represented the term is here compared with the whole galaxy
            share, base = count / size, doc_freq[t] / n
            return share * math.log(share / base)

        ranked = sorted(
            ((score(t, cnt), t) for t, cnt in term_count.items() if cnt >= min_support),
            key=lambda x: (-x[0], x[1]),
        )
        ranked = [r for r in ranked if r[0] > 0]
        label_terms = [display[t] for _, t in ranked[:2]]

        lang_count = Counter(lang for i in members for lang in person_langs(people[ids[i]])[:3])
        repo_count = Counter(
            name
            for i in members
            for name in {r.name for r in people[ids[i]].repos + people[ids[i]].contributed}
        )
        if not label_terms:  # nothing stands out: say what is most common instead
            label_terms = [lang for lang, cnt in lang_count.most_common(2) if cnt >= min_support]
        members_by_followers = sorted(
            members, key=lambda i: (-people[ids[i]].followers, ids[i])
        )
        out.append(
            {
                "id": c,
                "size": size,
                "label": ", ".join(label_terms) if label_terms else f"Cluster {c + 1}",
                "color": cluster_color(c),
                "top_langs": [lang for lang, _ in lang_count.most_common(top_n)],
                "top_members": [ids[i] for i in members_by_followers[:top_n]],
                "top_repos": [r for r, cnt in repo_count.most_common(top_n) if cnt >= 2],
            }
        )
    return out
