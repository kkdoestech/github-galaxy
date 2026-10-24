"""Command line.

  galaxy build <login>             write one galaxy JSON
  galaxy samples <login> [...]     write the demo samples the frontend ships with
  galaxy serve                     run the API (and the built frontend, if present)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from .cache import Cache
from .config import ROOT, load_settings
from .github import GitHubClient, GitHubError, GitHubSource
from .service import build


def _summary(galaxy: dict, points: int, seconds: float, out: Path) -> None:
    s, sp = galaxy["stats"], galaxy["spectral"]
    print(
        f"{galaxy['seed']}: {s['people']} people, {s['links']} links, {sp['k']} clusters "
        f"(auto {sp['k_auto']}, modularity {sp['modularity']}), "
        f"{points} API budget used, {seconds:.1f}s -> {out}"
    )
    for c in galaxy["clusters"]:
        print(f"  {c['id'] + 1:>2}. {c['label']:<34} {c['size']:>5}  {', '.join(c['top_members'])}")


async def _run(args: argparse.Namespace, logins: list[str]) -> list[tuple[dict, float]]:
    """Build each login in turn. Returns (galaxy, seconds) pairs; raises GitHubError."""
    settings = load_settings()
    cache = Cache(":memory:" if getattr(args, "no_cache", False) else settings.cache_path)
    client = GitHubClient(settings.token)
    source = GitHubSource(client, cache)
    results = []
    try:
        for login in logins:
            started = time.perf_counter()

            def progress(event: dict, started: float = started) -> None:
                print(f"  {time.perf_counter() - started:5.1f}s  {event['msg']}", file=sys.stderr)

            galaxy = await build(source, cache, login, args.depth, args.max, args.signal, progress)
            results.append((galaxy, time.perf_counter() - started))
    finally:
        await client.aclose()
    return results


async def _build(args: argparse.Namespace) -> int:
    try:
        [(galaxy, seconds)] = await _run(args, [args.login])
    except GitHubError as exc:
        print(f"error ({exc.code}): {exc.message}", file=sys.stderr)
        return 1
    out = Path(args.out or f"{args.login.lower()}.json")
    out.write_text(json.dumps(galaxy, separators=(",", ":")), encoding="utf-8")
    _summary(galaxy, galaxy["stats"]["api_points"], seconds, out)
    return 0


async def _samples(args: argparse.Namespace) -> int:
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        results = await _run(args, args.logins)
    except GitHubError as exc:
        print(f"error ({exc.code}): {exc.message}", file=sys.stderr)
        return 1
    index = []
    for galaxy, seconds in results:
        for node in galaxy["nodes"]:
            node["bio"] = None  # samples are redistributed: keep only what the view needs
        name = galaxy["seed"].lower()
        out = out_dir / f"{name}.json"
        out.write_text(json.dumps(galaxy, separators=(",", ":")), encoding="utf-8")
        _summary(galaxy, galaxy["stats"]["api_points"], seconds, out)
        index.append({"login": name, "people": galaxy["stats"]["people"],
                      "clusters": galaxy["spectral"]["k"]})
    (out_dir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="galaxy", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="crawl a user and write the galaxy JSON")
    b.add_argument("login")
    b.add_argument("--depth", type=int, default=2, choices=(1, 2, 3))
    b.add_argument("--max", type=int, default=800, help="max people (100-3000)")
    b.add_argument("--signal", default="collab", choices=("collab", "follow"))
    b.add_argument("--out", help="output file (default: <login>.json)")
    b.add_argument("--no-cache", action="store_true", help="ignore and don't write the cache")

    m = sub.add_parser("samples", help="write sample galaxies for the frontend demo")
    m.add_argument("logins", nargs="+")
    m.add_argument("--dir", default=str(ROOT / "frontend" / "public" / "samples"))
    m.add_argument("--depth", type=int, default=2, choices=(1, 2, 3))
    m.add_argument("--max", type=int, default=800)
    m.add_argument("--signal", default="collab", choices=("collab", "follow"))

    s = sub.add_parser("serve", help="run the API (and the built frontend, if present)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "build":
        return asyncio.run(_build(args))
    if args.cmd == "samples":
        return asyncio.run(_samples(args))

    import uvicorn

    uvicorn.run("galaxy.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
