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
    if values.size < 3:
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
            # Tied discrete histories can have MAD=IQR=0 without being truly
            # constant (for example [100, 100, 100, 100, 101]). A small scale
            # floor avoids flagging a value already inside the observed range,
            # while still detecting a material move away from that range.
            observed_min, observed_max = float(np.min(values)), float(np.max(values))
            scale = max(abs(median) * 0.01, np.finfo(float).eps)
            distance = max(observed_min - float(current), float(current) - observed_max, 0.0)
            score = 0.6745 * distance / scale
            method = "mad:tied_baseline_fallback"
            detail = f"mad=0, iqr=0, observed_range=[{observed_min:.3f}, {observed_max:.3f}], scale={scale:.3f}"
    return {"is_anomaly": bool(score > threshold), "score": float(score), "method": method, "reason": f"median={median:.3f}, {detail}, threshold={threshold}"}


def _trend_residual_detector(
    current: float,
    history: np.ndarray,
    *,
    expected_step: float,
    threshold: float,
) -> dict[str, Any] | None:
    """Judge a known trend by its next-step residual, not its raw level."""
    invalid = _invalid_current(current, "auto:trend")
    if invalid:
        return invalid

    historical_steps = np.diff(history)
    if historical_steps.size < 3:
        return None

    residuals = historical_steps - expected_step
    residual_median = float(np.median(residuals))
    residual_mad = float(np.median(np.abs(residuals - residual_median)))
    current_step = float(current) - float(history[-1])
    current_residual = current_step - expected_step

    if residual_mad > 0:
        score = 0.6745 * abs(current_residual - residual_median) / residual_mad
        detail = f"residual_mad={residual_mad:.3f}"
    else:
        residual_iqr = float(np.percentile(residuals, 75) - np.percentile(residuals, 25))
        if residual_iqr > 0:
            scale = residual_iqr / 1.349
            detail = f"residual_mad=0, residual_iqr={residual_iqr:.3f}"
        else:
            # A deterministic trend has zero residual spread. Use a small
            # metric-relative tolerance so floating-point noise does not page,
            # while a real flattening/reversal still produces a large score.
            scale = max(abs(expected_step) * 0.01, abs(float(history[-1])) * 1e-6, np.finfo(float).eps)
            detail = f"residual_mad=0, residual_iqr=0, scale={scale:.3f}"
        score = 0.6745 * abs(current_residual - residual_median) / scale

    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "auto:trend",
        "reason": (
            f"expected_step={expected_step:.3f}, current_step={current_step:.3f}, "
            f"residual_median={residual_median:.3f}, {detail}, threshold={threshold}"
        ),
    }


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
    selected_history = segment if segment.size >= 3 else full_history

    # ``trend`` is an expected step-over-step change. Comparing a steadily
    # growing metric with its historical *level* creates a false positive;
    # compare the newest step with historical step residuals instead.
    trend = context.get("trend")
    if trend is not None:
        try:
            expected_step = float(trend)
        except (TypeError, ValueError):
            expected_step = float("nan")
        if np.isfinite(expected_step):
            trend_result = _trend_residual_detector(
                current,
                selected_history,
                expected_step=expected_step,
                threshold=max(3.5, threshold),
            )
            if trend_result is not None:
                trend_result["reason"] += f"; history_size={selected_history.size}"
                if segment.size >= 3:
                    trend_result["reason"] += "; baseline=same_segment_history"
                if context.get("known_event"):
                    trend_result["reason"] += f"; known_event={context['known_event']}"
                return trend_result

    if segment.size >= 3:
        result = mad_detector(current, segment, threshold=max(3.5, threshold))
        result["method"] = f"auto:same_segment_{result['method']}"
        result["reason"] += f"; segment_size={segment.size}"
    elif full_history.size >= 3:
        result = mad_detector(current, full_history, threshold=max(3.5, threshold))
        result["method"] = f"auto:{result['method']}"
    else:
        result = zscore_detector(current, full_history, threshold=threshold)
        result["method"] = "auto:zscore"
    if context.get("known_event"):
        result["reason"] += f"; known_event={context['known_event']}"
    return result
