import math

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

from galaxy.graph import build_graph, collab_weights, component_of
from galaxy.labels import cluster_color, describe_clusters
from galaxy.layout import cluster_radii, layout
from galaxy.models import Person, RawGraph, Repo
from galaxy.pipeline import build_galaxy
from galaxy.spectral import cluster, laplacian_spectrum, modularity

from .synthetic import sbm_raw


@pytest.fixture(scope="module")
def sbm():
    return sbm_raw(blocks=4, size=60, p_in=0.25, p_out=0.01, seed=1)


def test_spectral_finds_planted_groups(sbm):
    raw, truth = sbm
    g = build_graph(raw, "follow")
    result = cluster(g.W)
    assert result.k_auto == 4
    assert result.k == 4
    order = [int(login[3:]) for login in g.ids]
    assert adjusted_rand_score(truth[order], result.labels) >= 0.9
    assert result.modularity > 0.5


def test_laplacian_eigenvalues_in_range(sbm):
    raw, _ = sbm
    g = build_graph(raw, "follow")
    lam, _ = laplacian_spectrum(g.W, 10, tau=0.0)
    assert np.all(lam >= 0) and np.all(lam <= 2)
    assert np.all(np.diff(lam) >= -1e-9)
    assert lam[0] == pytest.approx(0.0, abs=1e-8)
    lam_reg, _ = laplacian_spectrum(g.W, 10)
    assert lam_reg[0] < 0.6  # regularized: small but not exactly zero


def test_sparse_solver_matches_dense():
    raw, _ = sbm_raw(blocks=5, size=90, seed=3)  # 450 nodes -> eigsh path
    g = build_graph(raw, "follow")
    lam_sparse, _ = laplacian_spectrum(g.W, 8)
    dense = g.W.toarray()
    deg = dense.sum(1) + dense.sum(1).mean()
    A = dense / np.sqrt(np.outer(deg, deg))
    lam_dense = np.sort(1 - np.linalg.eigvalsh(A))[:8]
    assert np.allclose(lam_sparse, lam_dense, atol=1e-6)


def test_manual_k_override(sbm):
    raw, _ = sbm
    g = build_graph(raw, "follow")
    assert cluster(g.W, k=3).k == 3
    assert cluster(g.W, k=6).k == 6


def test_clusters_are_numbered_by_size(sbm):
    raw, _ = sbm
    labels = cluster(build_graph(raw, "follow").W, k=6).labels
    counts = np.bincount(labels)
    assert list(counts) == sorted(counts, reverse=True)


def test_same_input_same_output(sbm):
    raw, _ = sbm
    a = build_galaxy(raw)
    b = build_galaxy(raw)
    assert a == b


def test_tiny_graph_is_one_cluster():
    raw, _ = sbm_raw(blocks=1, size=8, p_in=0.6, seed=0)
    result = cluster(build_graph(raw).W)
    assert result.k == 1 and set(result.labels) == {0}


def test_modularity_of_single_cluster_is_zero(sbm):
    raw, _ = sbm
    g = build_graph(raw, "follow")
    assert modularity(g.W, np.zeros(len(g.ids), dtype=int)) == pytest.approx(0.0, abs=1e-12)


def _people(*logins):
    return {login: Person(login=login) for login in logins}


def test_follow_weights_and_link_direction():
    raw = RawGraph(seed="a", depth=1, max_people=10, people=_people("a", "b", "c"),
                   follows={("a", "b"), ("b", "a"), ("c", "a")})
    g = build_graph(raw, "follow")
    links = {(lk["source"], lk["target"]): lk for lk in g.links}
    assert links[("a", "b")]["kind"] == "mutual" and links[("a", "b")]["w"] == 1.0
    assert links[("c", "a")]["kind"] == "follow" and links[("c", "a")]["w"] == 0.5
    W = g.W.toarray()
    assert np.allclose(W, W.T) and np.all(np.diag(W) == 0)


def test_collab_weights_formula():
    people = _people("a", "b", "c", "d")
    people["a"].repos = [Repo("a/x")]
    people["b"].contributed = [Repo("a/x"), Repo("big/y")]
    people["c"].contributed = [Repo("big/y")]
    people["d"].contributed = [Repo("big/y")]
    raw = RawGraph(seed="a", depth=1, max_people=10, people=people, follows=set())
    w = collab_weights(raw)
    assert w[("a", "b")] == pytest.approx(1 / math.log2(3))  # a/x has 2 members
    # b, c, d share big/y with 3 members
    assert w[("b", "c")] == pytest.approx(1 / math.log2(4))
    assert ("a", "c") not in w


def test_collab_cap_and_mega_repo_ignored():
    people = _people(*[f"p{i}" for i in range(60)])
    for p in people.values():
        p.contributed = [Repo("huge/repo")] + [Repo(f"small/{j}") for j in range(10)]
    raw = RawGraph(seed="p0", depth=1, max_people=60, people=people, follows=set())
    w = collab_weights(raw)
    assert all(v <= 2.0 for v in w.values())
    two = RawGraph(seed="p0", depth=1, max_people=60,
                   people={k: people[k] for k in ("p0", "p1")}, follows=set())
    assert collab_weights(two)[("p0", "p1")] == 2.0  # capped


def test_component_of_keeps_seed_side():
    raw = RawGraph(seed="a", depth=1, max_people=10, people=_people("a", "b", "x", "y", "z"),
                   follows={("a", "b"), ("x", "y"), ("y", "z")})
    g = component_of(build_graph(raw), "a")
    assert g.ids == ["a", "b"]


def test_layout_keeps_clusters_apart(sbm):
    raw, _ = sbm
    g = build_graph(raw, "follow")
    labels = cluster(g.W).labels
    pos, centers = layout(g.W, labels, focus_index=0)
    radii = cluster_radii(np.bincount(labels))
    assert np.allclose(centers[labels[0]], 0)
    for a in range(len(centers)):
        for b in range(a + 1, len(centers)):
            assert np.linalg.norm(centers[a] - centers[b]) >= radii[a] + radii[b]
    for c in range(len(centers)):
        spread = np.linalg.norm(pos[labels == c] - centers[c], axis=1)
        assert spread.max() <= radii[c] * 1.25 + 1e-6


def test_cluster_labels_use_distinctive_terms(sbm):
    raw, _ = sbm
    g = build_graph(raw, "follow")
    labels = cluster(g.W).labels
    described = describe_clusters(raw.people, g.ids, labels)
    names = {d["label"] for d in described}
    assert len(names) == 4
    assert all("topic-" in d["label"] for d in described)
    assert sum(d["size"] for d in described) == len(g.ids)


def test_colors():
    assert cluster_color(0) == "#2C9DD7"
    colors = [cluster_color(c) for c in range(18)]
    assert len(set(colors)) == 18
    assert all(c.startswith("#") and len(c) == 7 for c in colors)


def test_galaxy_json_shape(sbm):
    raw, _ = sbm
    gal = build_galaxy(raw, "collab")
    assert gal["version"] == 1
    assert gal["seed"] == raw.seed
    assert gal["stats"]["people"] == len(gal["nodes"])
    node = gal["nodes"][0]
    assert set(node) >= {"id", "cluster", "pos", "followers", "hop", "repos", "langs"}
    assert len(node["pos"]) == 3
    ids = {n["id"] for n in gal["nodes"]}
    assert all(lk["source"] in ids and lk["target"] in ids for lk in gal["links"])
    assert gal["spectral"]["k"] == len(gal["clusters"])
