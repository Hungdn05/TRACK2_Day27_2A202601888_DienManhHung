from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _finite(values: Iterable[float]) -> np.ndarray:
    try:
        array = np.asarray(list(values), dtype=float)
    except (TypeError, ValueError):
        return np.asarray([], dtype=float)
    return array[np.isfinite(array)]


def _ks_statistic(current: np.ndarray, baseline: np.ndarray) -> float:
    values = np.sort(np.unique(np.concatenate([current, baseline])))
    current_cdf = np.searchsorted(np.sort(current), values, side="right") / current.size
    baseline_cdf = np.searchsorted(np.sort(baseline), values, side="right") / baseline.size
    return float(np.max(np.abs(current_cdf - baseline_cdf)))


def _ks_pvalue(statistic: float, current_n: int, baseline_n: int) -> float:
    """Two-sided asymptotic KS p-value with a finite-sample correction."""
    if statistic <= 0:
        return 1.0
    effective_n = np.sqrt((current_n * baseline_n) / (current_n + baseline_n))
    if effective_n == 0:
        return 1.0
    scaled = (effective_n + 0.12 + 0.11 / effective_n) * statistic
    terms = [(-1) ** (k - 1) * np.exp(-2.0 * (k * scaled) ** 2) for k in range(1, 101)]
    return float(np.clip(2.0 * sum(terms), 0.0, 1.0))


def detect_distribution_shift(current_values: Iterable[float], baseline_values: Iterable[float], *, ratio_threshold: float = 3.0) -> dict[str, Any]:
    """Detect shape or location drift without a SciPy dependency.

    ``ratio_threshold`` remains accepted for backwards compatibility.
    """
    current, baseline = _finite(current_values), _finite(baseline_values)
    if current.size < 2 or baseline.size < 2:
        return {"is_anomaly": False, "score": 0.0, "method": "ks_quantile", "reason": f"insufficient_history current_n={current.size}; baseline_n={baseline.size}"}
    ks = _ks_statistic(current, baseline)
    ks_pvalue = _ks_pvalue(ks, current.size, baseline.size)
    probabilities = np.asarray([0.1, 0.5, 0.9])
    baseline_quantiles, current_quantiles = np.quantile(baseline, probabilities), np.quantile(current, probabilities)
    iqr = float(np.quantile(baseline, 0.75) - np.quantile(baseline, 0.25))
    scale = iqr if iqr > 0 else max(abs(float(np.median(baseline))), 1.0)
    quantile_effect = float(np.mean(np.abs(current_quantiles - baseline_quantiles) / scale))
    # Small deterministic fixtures need a larger practical effect; for normal
    # batches, a 0.30 CDF gap or a statistically significant KS result is
    # actionable. Quantile movement catches tail/variance drift with equal mean.
    ks_threshold = 0.5 if min(current.size, baseline.size) < 4 else 0.30
    quantile_threshold = 1.0
    score = max(ks / ks_threshold, quantile_effect / quantile_threshold)
    significant_ks = bool(min(current.size, baseline.size) >= 4 and ks_pvalue < 0.05)
    return {"is_anomaly": bool(ks >= ks_threshold or significant_ks or quantile_effect >= quantile_threshold), "score": float(score), "method": "ks_quantile", "reason": f"ks={ks:.3f}/{ks_threshold:.3f}; ks_pvalue={ks_pvalue:.6f}; quantile_effect={quantile_effect:.3f}/{quantile_threshold:.3f}; baseline_iqr={iqr:.3f}; ignored_non_finite=true"}
