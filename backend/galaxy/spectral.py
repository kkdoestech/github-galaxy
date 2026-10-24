"""Spectral clustering on the normalized graph Laplacian.

Steps (Ng, Jordan & Weiss, with Qin & Rohe degree regularization):
  1. A = D_tau^-1/2 W D_tau^-1/2, where D_tau = D + tau*I and tau = mean degree.
  2. Laplacian L = I - A. Its smallest eigenvalues are 1 - (largest eigenvalues of A).
  3. k = number of eigenvalues before a big jump (the eigengap).
  4. Rows of the first k eigenvectors, L2-normalized, go into k-means.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import eigsh
from sklearn.cluster import KMeans

MIN_NODES = 12
K_MAX = 20
DENSE_LIMIT = 400  # below this, a dense eigensolver is simpler and just as fast


@dataclass
class SpectralResult:
    labels: np.ndarray  # cluster per node, 0 = largest cluster
    k: int
    k_auto: int
    eigenvalues: list[float]  # smallest Laplacian eigenvalues, ascending
    modularity: float


def laplacian_spectrum(
    W: sparse.csr_matrix, n_eig: int, tau: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Smallest `n_eig` eigenvalues of the regularized normalized Laplacian and their vectors."""
    n = W.shape[0]
    deg = np.asarray(W.sum(axis=1)).ravel()
    if tau is None:
        tau = float(deg.mean())
    reg = deg + tau
    reg[reg == 0] = 1.0  # isolated node with tau = 0: its row of A is all zeros anyway
    d = 1.0 / np.sqrt(reg)
    Dm = sparse.diags(d)
    A = (Dm @ W @ Dm).tocsr()
    n_eig = min(n_eig, n - 1)

    if n <= DENSE_LIMIT:
        mu, vecs = np.linalg.eigh(A.toarray())
        mu, vecs = mu[-n_eig:], vecs[:, -n_eig:]
    else:
        v0 = np.sqrt(reg)
        v0 /= np.linalg.norm(v0)
        mu, vecs = eigsh(A, k=n_eig, which="LA", v0=v0, tol=1e-8, maxiter=n * 20)

    order = np.argsort(-mu)
    lam = np.clip(1.0 - mu[order], 0.0, 2.0)
    return lam, vecs[:, order]


def modularity(W: sparse.csr_matrix, labels: np.ndarray) -> float:
    """Newman modularity of a partition of a weighted undirected graph."""
    two_m = W.sum()
    if two_m == 0:
        return 0.0
    n, k = W.shape[0], int(labels.max()) + 1
    M = sparse.csr_matrix((np.ones(n), (np.arange(n), labels)), shape=(n, k))
    inside = (M.T @ W @ M).diagonal()
    totals = np.asarray(M.T @ W.sum(axis=1)).ravel()
    return float(np.sum(inside / two_m - (totals / two_m) ** 2))


def relabel_by_size(labels: np.ndarray) -> np.ndarray:
    """Renumber clusters so 0 is the largest, ties broken by old id."""
    counts = np.bincount(labels)
    order = sorted(range(len(counts)), key=lambda c: (-counts[c], c))
    remap = np.empty(len(counts), dtype=int)
    remap[order] = np.arange(len(counts))
    return remap[labels]


def _kmeans(U: np.ndarray, k: int, seed: int) -> np.ndarray:
    X = U[:, :k].copy()
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    X /= norms
    return KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)


def cluster(
    W: sparse.csr_matrix, k: int | None = None, k_max: int = K_MAX, seed: int = 0
) -> SpectralResult:
    """Cluster the graph. With k=None, k is chosen from the eigengap.

    Real follow graphs are noisy, so the gap is not always clean. We take the three
    biggest gaps as candidates and keep the one whose partition has the best modularity.
    """
    n = W.shape[0]
    if n < MIN_NODES:
        labels = np.zeros(n, dtype=int)
        return SpectralResult(labels, 1, 1, [], modularity(W, labels) if n else 0.0)

    lam, U = laplacian_spectrum(W, k_max + 1)
    top = min(k_max, len(lam) - 1)
    gaps = np.diff(lam)  # gaps[k-1] = lam[k] - lam[k-1]: the jump after k small eigenvalues
    candidates = sorted(range(2, top + 1), key=lambda c: (-gaps[c - 1], c))[:3]

    scored = {}
    for c in candidates:
        labels_c = _kmeans(U, c, seed)
        scored[c] = (modularity(W, labels_c), labels_c)
    k_auto = max(candidates, key=lambda c: (scored[c][0], -c))

    if k is None:
        k_final, labels = k_auto, scored[k_auto][1]
    else:
        k_final = int(np.clip(k, 2, top))
        labels = scored[k_final][1] if k_final in scored else _kmeans(U, k_final, seed)

    labels = relabel_by_size(labels)
    return SpectralResult(
        labels=labels,
        k=int(labels.max()) + 1,
        k_auto=k_auto,
        eigenvalues=[round(float(x), 5) for x in lam],
        modularity=round(modularity(W, labels), 4),
    )
