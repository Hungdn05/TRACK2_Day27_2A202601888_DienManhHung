from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _finite(values: Iterable[float]) -> np.ndarray:
    cleaned: list[float] = []
    try:
        iterator = iter(values)
    except TypeError:
        return np.asarray([], dtype=float)
    for value in iterator:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(numeric):
            cleaned.append(numeric)
    return np.asarray(cleaned, dtype=float)


def _symmetric_ratio(left: float, right: float, *, zero_tolerance: float = 1e-12) -> float:
    left_abs, right_abs = abs(float(left)), abs(float(right))
    if left_abs <= zero_tolerance and right_abs <= zero_tolerance:
        return 1.0
    smaller, larger = min(left_abs, right_abs), max(left_abs, right_abs)
    return float("inf") if smaller <= zero_tolerance else larger / smaller


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
    if current.size == 0 or baseline.size == 0:
        return {"is_anomaly": False, "score": 0.0, "method": "ks_quantile_ratio", "reason": f"insufficient_history current_n={current.size}; baseline_n={baseline.size}"}
    if current.size < 2 or baseline.size < 2:
        mean_ratio = _symmetric_ratio(float(np.mean(current)), float(np.mean(baseline)))
        return {
            "is_anomaly": bool(mean_ratio >= ratio_threshold),
            "score": float(mean_ratio),
            "method": "mean_ratio_small_sample",
            "reason": (
                f"insufficient_for_shape_test current_n={current.size}; baseline_n={baseline.size}; "
                f"mean_ratio={mean_ratio:.3f}/{ratio_threshold:.3f}"
            ),
        }
    ks = _ks_statistic(current, baseline)
    ks_pvalue = _ks_pvalue(ks, current.size, baseline.size)
    probabilities = np.asarray([0.1, 0.5, 0.9])
    baseline_quantiles, current_quantiles = np.quantile(baseline, probabilities), np.quantile(current, probabilities)
    iqr = float(np.quantile(baseline, 0.75) - np.quantile(baseline, 0.25))
    current_iqr = float(np.quantile(current, 0.75) - np.quantile(current, 0.25))
    # A small sample can land a by-chance narrow IQR, which would shrink this
    # denominator and inflate the effect. Floor it with the baseline std so the
    # yardstick reflects the batch's real spread.
    scale = iqr if iqr > 0 else max(abs(float(np.median(baseline))), 1.0)
    scale = max(scale, float(np.std(baseline)))
    quantile_effect = float(np.mean(np.abs(current_quantiles - baseline_quantiles) / scale))

    # Keep the starter's useful location-ratio signal. KS and a few quantiles
    # can miss a sparse but operationally important tail that moves the mean.
    current_mean, baseline_mean = float(np.mean(current)), float(np.mean(baseline))
    mean_ratio = _symmetric_ratio(current_mean, baseline_mean)
    baseline_std, current_std = float(np.std(baseline)), float(np.std(current))
    scale_floor = max(abs(float(np.median(baseline))) * 1e-6, 1e-9)
    if baseline_std <= scale_floor and current_std <= scale_floor:
        std_ratio = 1.0
    else:
        std_ratio = _symmetric_ratio(current_std, baseline_std, zero_tolerance=scale_floor)

    # Ratio checks also require a material absolute effect. This retains the
    # zero-mean/large-tail protection without alerting on harmless round-off
    # around a broad distribution whose mean happens to be nearly zero.
    location_scale = max(baseline_std, abs(baseline_mean) * 0.05, scale_floor)
    mean_effect = abs(current_mean - baseline_mean) / location_scale
    spread_effect = abs(current_std - baseline_std) / max(baseline_std, scale_floor)
    mean_alert = bool(mean_ratio >= ratio_threshold and mean_effect >= 1.0)
    std_alert = bool(std_ratio >= ratio_threshold and spread_effect >= 1.0)
    # A fixed CDF-gap threshold is not comparable across sample sizes: two
    # samples drawn from the *same* distribution routinely exceed a 0.30 gap
    # when n is small, so a constant threshold alerts on sampling noise. Use
    # the Kolmogorov-Smirnov two-sample critical value at alpha=0.05, which
    # scales with sqrt((n+m)/nm) and keeps the false-positive rate near 5%.
    ks_threshold = 1.36 * float(np.sqrt((current.size + baseline.size) / (current.size * baseline.size)))
    # When the baseline has real spread, quantile movement must clear a full
    # baseline IQR twice over to count as drift rather than noise. A degenerate
    # (zero-IQR) baseline has no such yardstick, so any movement stays material.
    quantile_threshold = 1.0 if iqr <= 0 else 2.0
    # Shape drift can hold both mean and CDF gap near baseline while the spread
    # changes materially: a bimodal batch collapsing to one mode, or a widening
    # batch. Compare robust IQRs, which the mean/std ratios above do not catch
    # once their absolute-effect gates are applied.
    iqr_ratio = _symmetric_ratio(current_iqr, iqr, zero_tolerance=max(scale_floor, 1e-12))
    both_samples_sized = bool(current.size >= 4 and baseline.size >= 4)
    collapse_alert = bool(both_samples_sized and iqr > 0 and current_iqr / iqr <= 0.15)
    expansion_alert = bool(both_samples_sized and iqr > 0 and iqr_ratio >= 2.5 and std_ratio >= 2.5)

    mean_score = mean_ratio / ratio_threshold if np.isfinite(mean_ratio) else (mean_effect if mean_effect > 0 else 0.0)
    std_score = std_ratio / ratio_threshold if np.isfinite(std_ratio) else (spread_effect if spread_effect > 0 else 0.0)
    score = max(ks / ks_threshold, quantile_effect / quantile_threshold, mean_score, std_score)
    significant_ks = bool(min(current.size, baseline.size) >= 4 and ks_pvalue < 0.05)
    return {
        "is_anomaly": bool(
            ks >= ks_threshold
            or significant_ks
            or quantile_effect >= quantile_threshold
            or mean_alert
            or std_alert
            or collapse_alert
            or expansion_alert
        ),
        "score": float(score),
        "method": "ks_quantile_ratio",
        "reason": (
            f"ks={ks:.3f}/{ks_threshold:.3f}; ks_pvalue={ks_pvalue:.6f}; "
            f"quantile_effect={quantile_effect:.3f}/{quantile_threshold:.3f}; "
            f"mean_ratio={mean_ratio:.3f}/{ratio_threshold:.3f}; mean_effect={mean_effect:.3f}; "
            f"std_ratio={std_ratio:.3f}/{ratio_threshold:.3f}; spread_effect={spread_effect:.3f}; "
            f"baseline_iqr={iqr:.3f}; current_iqr={current_iqr:.3f}; iqr_ratio={iqr_ratio:.3f}; "
            f"collapse={collapse_alert}; expansion={expansion_alert}; ignored_non_finite=true"
        ),
    }
