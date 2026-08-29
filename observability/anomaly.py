"""Statistical anomaly detectors with a stable public return shape."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _finite_values(values: Iterable[float]) -> np.ndarray:
    try:
        array = np.asarray(list(values), dtype=float)
    except (TypeError, ValueError):
        return np.asarray([], dtype=float)
    return array[np.isfinite(array)]


def _invalid_current(current: float, method: str) -> dict[str, Any] | None:
    try:
        value = float(current)
    except (TypeError, ValueError):
        value = float("nan")
    if not np.isfinite(value):
        return {"is_anomaly": True, "score": float("inf"), "method": method, "reason": "invalid_current"}
    return None


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    invalid = _invalid_current(current, "zscore")
    if invalid:
        return invalid
    values = _finite_values(history)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean, std = float(np.mean(values)), float(np.std(values))
    score = float("inf") if std == 0 and float(current) != mean else (0.0 if std == 0 else abs(float(current) - mean) / std)
    return {"is_anomaly": bool(score > threshold), "score": float(score), "method": "zscore", "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}"}


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    invalid = _invalid_current(current, "mad")
    if invalid:
        return invalid
    values = _finite_values(history)
    if values.size < 5:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad > 0:
        score, method, detail = 0.6745 * abs(float(current) - median) / mad, "mad", f"mad={mad:.3f}"
    else:
        iqr = float(np.percentile(values, 75) - np.percentile(values, 25))
        if iqr > 0:
            score, method, detail = abs(float(current) - median) / (iqr / 1.349), "mad:iqr_fallback", f"mad=0, iqr={iqr:.3f}"
        else:
            score, method, detail = (float("inf") if float(current) != median else 0.0), "mad:constant_baseline", "mad=0, constant_baseline=true"
    return {"is_anomaly": bool(score > threshold), "score": float(score), "method": method, "reason": f"median={median:.3f}, {detail}, threshold={threshold}"}


def detect_anomaly(current: float, history: Iterable[float], *, method: str = "auto", threshold: float = 3.0, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect metric anomalies; ``auto`` prefers a seasonal robust baseline."""
    if method == "zscore":
        return zscore_detector(current, history, threshold=threshold)
    if method == "mad":
        return mad_detector(current, history, threshold=max(3.5, threshold))
    if method != "auto":
        raise ValueError(f"Unsupported method: {method}")
    context = context or {}
    segment, full_history = _finite_values(context.get("same_segment_history", [])), _finite_values(history)
    if segment.size >= 5:
        result = mad_detector(current, segment, threshold=max(3.5, threshold))
        result["method"] = f"auto:same_segment_{result['method']}"
        result["reason"] += f"; segment_size={segment.size}"
    elif full_history.size >= 5:
        result = mad_detector(current, full_history, threshold=max(3.5, threshold))
        result["method"] = f"auto:{result['method']}"
    else:
        result = zscore_detector(current, full_history, threshold=threshold)
        result["method"] = "auto:zscore"
    if context.get("known_event"):
        result["reason"] += f"; known_event={context['known_event']}"
    return result
