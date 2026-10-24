"""An in-memory stand-in for GitHub."""

from __future__ import annotations

from galaxy.github import Edges
from galaxy.models import Person, Repo


class FakeSource:
    def __init__(self, following: dict[str, list[str]], orgs: set[str] = frozenset()):
        self.following = following
        self.orgs = set(orgs)
        self.followers: dict[str, list[str]] = {u: [] for u in following}
        for a, outs in following.items():
            for b in outs:
                self.followers.setdefault(b, []).append(a)
        self.following_total: dict[str, int] = {}  # override reported counts
        self.points = 0
        self.queries = 0
        self.edge_calls: list[str] = []
        self.profile_calls: list[str] = []

    def users(self) -> set[str]:
        return set(self.following) | set(self.followers)

    async def owner(self, login):
        self.queries += 1
        for u in self.users() | self.orgs:
            if u.lower() == login.lower():
                return u, "Organization" if u in self.orgs else "User"
        return None

    async def edges(self, logins, following_cap, followers_cap, followers_max_total,
                    on_progress=None):
        self.queries += 1
        self.points += 1
        out = {}
        for login in logins:
            self.edge_calls.append(login)
            fol = self.followers.get(login, [])
            out[login] = Edges(
                following=self.following.get(login, [])[:following_cap],
                followers=fol[:followers_cap] if len(fol) <= followers_max_total else [],
                following_total=self.following_total.get(login, len(self.following.get(login, []))),
                followers_total=len(fol),
            )
        if on_progress:
            await on_progress(len(logins), len(logins))
        return out

    async def profiles(self, logins, with_contrib=frozenset(), on_progress=None):
        self.queries += 1
        self.points += 1
        self.profile_calls += logins
        self.contrib_calls = getattr(self, "contrib_calls", []) + [
            login for login in logins if login in with_contrib
        ]
        if on_progress:
            await on_progress(len(logins), len(logins))
        return {
            login: Person(login=login, followers=len(self.followers.get(login, [])),
                          following=self.following_total.get(
                              login, len(self.following.get(login, []))),
                          repos=[Repo(f"{login}/r", lang="Go")])
            if login in self.users() else None
            for login in logins
        }
