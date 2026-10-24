"""3D positions: clusters as separate groups of stars, related clusters closer together."""

from __future__ import annotations

import networkx as nx
import numpy as np
from scipy import sparse

STAR_SPACING = 22.0  # cluster radius = STAR_SPACING * size^(1/3)
CLUSTER_GAP = 1.35  # minimum center distance, as a multiple of the two radii


def cluster_radii(sizes: np.ndarray) -> np.ndarray:
    return STAR_SPACING * np.cbrt(np.maximum(sizes, 1))


def _separate(centers: np.ndarray, radii: np.ndarray, rounds: int = 300) -> np.ndarray:
    """Push overlapping cluster spheres apart until none overlap."""
    centers = centers.copy()
    k = len(centers)
    rng = np.random.default_rng(0)
    for _ in range(rounds):
        moved = False
        for a in range(k):
            for b in range(a + 1, k):
                delta = centers[b] - centers[a]
                dist = float(np.linalg.norm(delta))
                need = (radii[a] + radii[b]) * CLUSTER_GAP
                if dist >= need:
                    continue
                if dist < 1e-9:
                    delta, dist = rng.normal(size=3), 1.0
                    delta /= np.linalg.norm(delta)
                else:
                    delta = delta / dist
                push = (need - dist) / 2
                centers[a] -= delta * push
                centers[b] += delta * push
                moved = True
        if not moved:
            break
    return centers


def cluster_centers(W: sparse.csr_matrix, labels: np.ndarray, seed: int = 0) -> np.ndarray:
    k = int(labels.max()) + 1
    sizes = np.bincount(labels, minlength=k)
    radii = cluster_radii(sizes)
    if k == 1:
        return np.zeros((1, 3))

    n = len(labels)
    M = sparse.csr_matrix((np.ones(n), (np.arange(n), labels)), shape=(n, k))
    between = (M.T @ W @ M).toarray()
    G = nx.Graph()
    G.add_nodes_from(range(k))
    for a in range(k):
        for b in range(a + 1, k):
            if between[a, b] > 0:
                G.add_edge(a, b, weight=between[a, b] / np.sqrt(sizes[a] * sizes[b]))
    pos = nx.spring_layout(G, dim=3, seed=seed, weight="weight")
    centers = np.array([pos[c] for c in range(k)], dtype=float)
    centers -= centers.mean(axis=0)
    spread = np.abs(centers).max() or 1.0
    centers *= radii.sum() / spread / 2
    return _separate(centers, radii)


def cluster_inner(W: sparse.csr_matrix, members: np.ndarray, radius: float, seed: int = 0):
    """Positions of one cluster's members around (0,0,0), within about `radius`."""
    if len(members) == 1:
        return np.zeros((1, 3))
    sub = W[members][:, members]
    G = nx.from_scipy_sparse_array(sub)
    iterations = 50 if len(members) <= 500 else 30
    pos = nx.spring_layout(G, dim=3, seed=seed, iterations=iterations)
    P = np.array([pos[i] for i in range(len(members))], dtype=float)
    P -= P.mean(axis=0)
    norms = np.linalg.norm(P, axis=1)
    scale = np.percentile(norms, 95) or 1.0
    P *= radius / scale
    # pull far outliers (isolated members) back toward the cluster edge
    norms = np.linalg.norm(P, axis=1, keepdims=True)
    limit = radius * 1.25
    P = np.where(norms > limit, P / np.maximum(norms, 1e-9) * limit, P)
    return P


def layout(
    W: sparse.csr_matrix, labels: np.ndarray, focus_index: int | None = None, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Return (node positions n x 3, cluster centers k x 3). The focus node's cluster is at 0."""
    n = len(labels)
    k = int(labels.max()) + 1 if n else 0
    if n == 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    sizes = np.bincount(labels, minlength=k)
    radii = cluster_radii(sizes)
    centers = cluster_centers(W, labels, seed)
    if focus_index is not None:
        centers -= centers[labels[focus_index]]

    positions = np.zeros((n, 3))
    for c in range(k):
        members = np.flatnonzero(labels == c)
        positions[members] = cluster_inner(W, members, radii[c], seed) + centers[c]
    return positions, centers
