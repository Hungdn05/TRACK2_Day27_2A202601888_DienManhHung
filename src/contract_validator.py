"""Deterministic data-contract validation used by the stable student API."""
from __future__ import annotations

import math
import numbers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DEFAULT_ACTIONS = {"critical": "block", "warning": "warn", "info": "warn"}


def _serializable_indices(mask: pd.Series) -> list[Any]:
    indices: list[Any] = []
    for value in mask.index[mask].tolist():
        indices.append(value.item() if hasattr(value, "item") else value)
    return indices


def _issue(
    check: str,
    *,
    column: str | None,
    severity: str,
    passed: bool,
    details: str,
    action: str | None = None,
    invalid_mask: pd.Series | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "check": check,
        "column": column,
        "severity": severity,
        "passed": bool(passed),
        "details": details,
        "action": action or DEFAULT_ACTIONS.get(severity, "warn"),
    }
    if invalid_mask is not None:
        result["invalid_count"] = int(invalid_mask.sum())
        result["invalid_indices"] = _serializable_indices(invalid_mask)
    return result


def load_contract(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _datetime_values(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce", format="mixed")


def _type_invalid_mask(series: pd.Series, expected_type: str) -> pd.Series:
    present = series.notna()
    if expected_type == "string":
        valid = series.map(lambda value: isinstance(value, str) if pd.notna(value) else True)
    elif expected_type == "integer":
        valid = series.map(
            lambda value: (
                isinstance(value, numbers.Integral)
                and not isinstance(value, bool)
            )
            or (
                isinstance(value, numbers.Real)
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value).is_integer()
            )
            if pd.notna(value)
            else True
        )
    elif expected_type == "number":
        valid = series.map(
            lambda value: (
                isinstance(value, numbers.Real)
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            )
            if pd.notna(value)
            else True
        )
    elif expected_type == "datetime":
        valid = _datetime_values(series).notna() | ~present
    else:
        return pd.Series(False, index=series.index)
    return present & ~valid.astype(bool)


def _rules(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    # Orders uses ``columns`` while the KB contract uses ``fields``.
    return contract.get("columns") or contract.get("fields") or {}


def validate_dataframe(
    df: pd.DataFrame,
    contract: dict[str, Any],
    *,
    now: datetime | pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Validate a dataframe without coercing away type drift."""
    issues: list[dict[str, Any]] = []
    for column, rules in _rules(contract).items():
        severity = str(rules.get("severity", "warning"))
        action = str(rules.get("action", DEFAULT_ACTIONS.get(severity, "warn")))
        required = bool(rules.get("required", False))
        if column not in df.columns:
            if required:
                issues.append(_issue("required_column", column=column, severity=severity, passed=False, details=f"Missing required column: {column}", action=action))
            continue

        series = df[column]
        if required:
            null_mask = series.isna()
            issues.append(_issue("not_null", column=column, severity=severity, passed=not bool(null_mask.any()), details=f"null_count={int(null_mask.sum())}", action=action, invalid_mask=null_mask))

        expected_type = rules.get("type")
        if expected_type:
            invalid_mask = _type_invalid_mask(series, str(expected_type))
            issues.append(_issue("type", column=column, severity=severity, passed=not bool(invalid_mask.any()), details=f"expected_type={expected_type}; invalid_count={int(invalid_mask.sum())}", action=action, invalid_mask=invalid_mask))

        if rules.get("unique"):
            duplicate_mask = series.notna() & series.duplicated(keep=False)
            issues.append(_issue("unique", column=column, severity=severity, passed=not bool(duplicate_mask.any()), details=f"duplicate_rows={int(duplicate_mask.sum())}", action=action, invalid_mask=duplicate_mask))

        accepted = rules.get("accepted_values")
        if accepted is not None:
            invalid_mask = series.notna() & ~series.isin(accepted)
            issues.append(_issue("accepted_values", column=column, severity=severity, passed=not bool(invalid_mask.any()), details=f"invalid_count={int(invalid_mask.sum())}; accepted={accepted}", action=action, invalid_mask=invalid_mask))

        if "min" in rules or "max" in rules:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid_mask = pd.Series(False, index=series.index)
            if "min" in rules:
                invalid_mask |= numeric < rules["min"]
            if "max" in rules:
                invalid_mask |= numeric > rules["max"]
            issues.append(_issue("range", column=column, severity=severity, passed=not bool(invalid_mask.any()), details=f"invalid_count={int(invalid_mask.sum())}", action=action, invalid_mask=invalid_mask))

        if "min_length" in rules:
            length = series.astype("string").str.len()
            invalid_mask = series.notna() & (length < int(rules["min_length"]))
            issues.append(_issue("min_length", column=column, severity=severity, passed=not bool(invalid_mask.any()), details=f"min_length={rules['min_length']}; invalid_count={int(invalid_mask.sum())}", action=action, invalid_mask=invalid_mask))

    freshness = contract.get("freshness")
    if freshness:
        column = str(freshness.get("column"))
        severity = str(freshness.get("severity", "warning"))
        action = str(freshness.get("action", DEFAULT_ACTIONS.get(severity, "warn")))
        if column not in df.columns:
            issues.append(_issue("freshness", column=column, severity=severity, passed=False, details=f"freshness column is missing: {column}", action=action))
        else:
            latest = _datetime_values(df[column]).max()
            if pd.isna(latest):
                issues.append(_issue("freshness", column=column, severity=severity, passed=False, details="no parseable timestamp available for freshness", action=action))
            else:
                reference = pd.Timestamp(now or datetime.now(timezone.utc))
                reference = reference.tz_localize("UTC") if reference.tzinfo is None else reference.tz_convert("UTC")
                age_minutes = (reference - latest).total_seconds() / 60.0
                max_delay = float(freshness.get("max_delay_minutes", 0))
                issues.append(_issue("freshness", column=column, severity=severity, passed=bool(age_minutes <= max_delay), details=f"latest={latest.isoformat()}; age_minutes={age_minutes:.3f}; max_delay_minutes={max_delay:.3f}", action=action))
    return issues


def failed_issues(issues: list[dict[str, Any]], min_severity: str | None = None) -> list[dict[str, Any]]:
    failed = [issue for issue in issues if not issue.get("passed", False)]
    if min_severity is None:
        return failed
    order = {"info": 0, "warning": 1, "critical": 2}
    return [issue for issue in failed if order.get(issue.get("severity", "warning"), 1) >= order[min_severity]]


def quarantine_rows(df: pd.DataFrame, issues: list[dict[str, Any]]) -> pd.DataFrame:
    """Return identifiable invalid rows for local remediation/evidence."""
    indices: set[Any] = set()
    for issue in issues:
        if not issue.get("passed", False):
            indices.update(issue.get("invalid_indices", []))
    return df.loc[df.index.isin(indices)].copy() if indices else df.iloc[0:0].copy()
