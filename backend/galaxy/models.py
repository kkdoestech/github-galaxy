"""Plain data types shared by the crawler and the pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Repo:
    name: str  # "owner/name"
    stars: int = 0
    lang: str | None = None
    topics: list[str] = field(default_factory=list)


@dataclass
class Person:
    login: str
    name: str | None = None
    avatar: str | None = None
    bio: str | None = None
    followers: int = 0
    following: int = 0
    hop: int = 0
    repos: list[Repo] = field(default_factory=list)  # owned, most-starred first
    contributed: list[Repo] = field(default_factory=list)  # recently contributed to

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Person:
        d = dict(d)
        d["repos"] = [Repo(**r) for r in d.get("repos", [])]
        d["contributed"] = [Repo(**r) for r in d.get("contributed", [])]
        return cls(**d)


@dataclass
class RawGraph:
    """Everything the crawler learned. Cached so re-clustering never re-crawls."""

    seed: str
    depth: int
    max_people: int
    people: dict[str, Person] = field(default_factory=dict)
    follows: set[tuple[str, str]] = field(default_factory=set)  # (follower, followee)
    api_points: int = 0
    queries: int = 0
    built_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "depth": self.depth,
            "max_people": self.max_people,
            "people": {k: asdict(p) for k, p in self.people.items()},
            "follows": sorted(list(f) for f in self.follows),
            "api_points": self.api_points,
            "queries": self.queries,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RawGraph:
        return cls(
            seed=d["seed"],
            depth=d["depth"],
            max_people=d["max_people"],
            people={k: Person.from_dict(p) for k, p in d["people"].items()},
            follows={(a, b) for a, b in d["follows"]},
            api_points=d.get("api_points", 0),
            queries=d.get("queries", 0),
            built_at=d.get("built_at", ""),
        )
