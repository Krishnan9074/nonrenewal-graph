import numpy as np
import pandas as pd


def nearest(treated: pd.DataFrame, pool: pd.DataFrame, cols: list[str], k: int = 5) -> list[str]:
    """Union of each treated row's k nearest pool rows in standardized feature space; index values are the ids."""
    both = pd.concat([treated[cols], pool[cols]])
    mu, sd = both.mean(), both.std().replace(0, 1)
    t = ((treated[cols] - mu) / sd).to_numpy(dtype=float)
    p = ((pool[cols] - mu) / sd).to_numpy(dtype=float)
    d = np.linalg.norm(t[:, None, :] - p[None, :, :], axis=2)
    picks = np.argsort(d, axis=1)[:, : min(k, len(pool))]
    return sorted({pool.index[i] for row in picks for i in row})
