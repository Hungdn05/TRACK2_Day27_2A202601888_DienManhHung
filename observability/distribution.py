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


def detect_distribution_shift(current_values: Iterable[float], baseline_values: Iterable[float], *, ratio_threshold: float = 3.0) -> dict[str, Any]:
    """Detect shape or location drift without a SciPy dependency.

    ``ratio_threshold`` remains accepted for backwards compatibility.
    """
    current, baseline = _finite(current_values), _finite(baseline_values)
    if current.size < 4 or baseline.size < 4:
        return {"is_anomaly": False, "score": 0.0, "method": "ks_quantile", "reason": f"insufficient_history current_n={current.size}; baseline_n={baseline.size}"}
    ks = _ks_statistic(current, baseline)
    probabilities = np.asarray([0.1, 0.5, 0.9])
    baseline_quantiles, current_quantiles = np.quantile(baseline, probabilities), np.quantile(current, probabilities)
    iqr = float(np.quantile(baseline, 0.75) - np.quantile(baseline, 0.25))
    scale = iqr if iqr > 0 else max(abs(float(np.median(baseline))), 1.0)
    quantile_effect = float(np.mean(np.abs(current_quantiles - baseline_quantiles) / scale))
    ks_threshold, quantile_threshold = 0.35, 1.5
    score = max(ks / ks_threshold, quantile_effect / quantile_threshold)
    return {"is_anomaly": bool(ks >= ks_threshold or quantile_effect >= quantile_threshold), "score": float(score), "method": "ks_quantile", "reason": f"ks={ks:.3f}/{ks_threshold:.3f}; quantile_effect={quantile_effect:.3f}/{quantile_threshold:.3f}; baseline_iqr={iqr:.3f}; ignored_non_finite=true"}
