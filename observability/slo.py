from __future__ import annotations

import math
from typing import Any


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    if not isinstance(target, (int, float)) or not math.isfinite(float(target)) or not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")
    allowed_bad_rate = 1.0 - target
    if total_events == 0:
        return {
            "target": target,
            "actual_bad_rate": 0.0,
            "allowed_bad_rate": allowed_bad_rate,
            "burn_rate": 0.0,
            "remaining_error_budget_fraction": 1.0,
            "breached": False,
        }
    actual_bad_rate = bad_events / total_events
    burn_rate = actual_bad_rate / allowed_bad_rate
    consumed_fraction = min(1.0, actual_bad_rate / allowed_bad_rate)
    return {
        "target": target,
        "actual_bad_rate": actual_bad_rate,
        "allowed_bad_rate": allowed_bad_rate,
        "burn_rate": burn_rate,
        "remaining_error_budget_fraction": max(0.0, 1.0 - consumed_fraction),
        "breached": bool(actual_bad_rate > allowed_bad_rate),
    }


def evaluate_multiwindow_burn(
    *,
    short_window_burn: float,
    long_window_burn: float,
    policy: str = "starter",
) -> dict[str, Any]:
    """Apply a two-window burn-rate policy inspired by Google SRE guidance."""
    for name, value in (("short_window_burn", short_window_burn), ("long_window_burn", long_window_burn)):
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"{name} must be a finite non-negative number")
    short, long = float(short_window_burn), float(long_window_burn)
    if short >= 14.4 and long >= 14.4:
        page, severity, reason = True, "critical", "fast_burn: both windows are at least 14.4x"
    elif short >= 6.0 and long >= 6.0:
        page, severity, reason = True, "critical", "sustained_burn: both windows are at least 6x"
    elif short >= 1.0 and long >= 1.0:
        page, severity, reason = False, "warning", "ticket: budget is burning but paging threshold is not met"
    else:
        page, severity, reason = False, "info", "healthy_or_transient: both-window confirmation is absent"
    return {
        "page": page,
        "severity": severity,
        "reason": reason,
        "policy": policy,
        "short_window_burn": short,
        "long_window_burn": long,
    }
