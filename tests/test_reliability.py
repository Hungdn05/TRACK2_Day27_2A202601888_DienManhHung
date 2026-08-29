from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from observability.anomaly import detect_anomaly
from observability.lineage import extract_dbt_dataset_graph
from src.contract_validator import load_contract, quarantine_rows, validate_dataframe
from student_api import (
    column_downstream,
    detect_distribution,
    multiwindow_burn,
    rag_embedding_shift,
)

ROOT = Path(__file__).resolve().parents[1]


def healthy_orders() -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    return pd.DataFrame([{
        "order_id": 1,
        "customer_id": "C1",
        "amount": 10.0,
        "currency": "USD",
        "status": "completed",
        "created_at": (now - timedelta(minutes=10)).isoformat(),
        "updated_at": (now - timedelta(minutes=5)).isoformat(),
    }])


def test_contract_detects_type_freshness_and_exposes_action():
    df = healthy_orders()
    df = df.astype({"order_id": "object", "amount": "object"})
    df.loc[0, "order_id"] = "1"
    df.loc[0, "amount"] = "not-a-number"
    df.loc[0, "updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    issues = validate_dataframe(df, load_contract(ROOT / "contracts" / "orders_contract.yaml"))
    failed = [issue for issue in issues if not issue["passed"]]
    assert {(issue["check"], issue["column"]) for issue in failed} >= {("type", "order_id"), ("type", "amount"), ("freshness", "updated_at")}
    assert all(issue["action"] in {"block", "warn", "quarantine"} for issue in failed)


def test_contract_detects_missing_required_and_malformed_datetime():
    df = healthy_orders().drop(columns=["customer_id"])
    df.loc[0, "created_at"] = "not-a-timestamp"
    failed = [issue for issue in validate_dataframe(df, load_contract(ROOT / "contracts" / "orders_contract.yaml")) if not issue["passed"]]
    assert ("required_column", "customer_id") in {(issue["check"], issue["column"]) for issue in failed}
    assert ("type", "created_at") in {(issue["check"], issue["column"]) for issue in failed}


def test_contract_quarantines_identifiable_duplicate_rows():
    df = pd.concat([healthy_orders(), healthy_orders()], ignore_index=True)
    df.loc[1, "order_id"] = df.loc[0, "order_id"]
    issues = validate_dataframe(df, load_contract(ROOT / "contracts" / "orders_contract.yaml"))
    assert len(quarantine_rows(df, issues)) == 2


def test_auto_detector_uses_same_weekday_baseline():
    result = detect_anomaly(250, [600, 610, 590, 605, 595, 620], context={"same_segment_history": [245, 250, 255, 252, 248]})
    assert result["is_anomaly"] is False
    assert result["method"].startswith("auto:same_segment")


def test_auto_detector_uses_short_segment_and_handles_tied_baseline():
    short_segment = detect_anomaly(250, [600, 610, 590, 605], context={"same_segment_history": [245, 250, 255]})
    assert short_segment["is_anomaly"] is False
    assert short_segment["method"].startswith("auto:same_segment")
    assert detect_anomaly(101, [100, 100, 100, 100, 101], method="mad")["is_anomaly"] is False
    assert detect_anomaly(150, [100, 100, 100, 100, 101], method="mad")["is_anomaly"] is True


def test_auto_detector_honors_known_numeric_trend():
    history = [1000, 1020, 1040, 1060, 1080, 1100, 1120]
    continuing = detect_anomaly(1140, history, context={"trend": 20})
    flattening = detect_anomaly(1120, history, context={"trend": 20})
    reversal = detect_anomaly(850, history, context={"trend": 20})
    assert continuing["is_anomaly"] is False
    assert continuing["method"] == "auto:trend"
    assert flattening["is_anomaly"] is True
    assert reversal["is_anomaly"] is True


def test_constant_baseline_and_shape_shift_are_detected():
    assert detect_anomaly(150, [100, 100, 100, 100, 100], method="mad")["is_anomaly"] is True
    assert detect_distribution([0, 0, 20, 20], [9, 10, 10, 11])["is_anomaly"] is True


def test_distribution_handles_small_samples_and_moderate_shape_drift():
    assert detect_distribution([40], [10])["is_anomaly"] is True
    assert detect_distribution([20], [10])["is_anomaly"] is False
    assert detect_distribution([10], [10])["is_anomaly"] is False
    assert detect_distribution([20, 20, 20], [10, 10, 10])["is_anomaly"] is True
    assert detect_distribution([0, 5, 5, 5, 5, 10], [0, 0, 0, 10, 10, 10])["is_anomaly"] is True
    assert detect_distribution([9, 10, 10, 11], [9, 10, 10, 11])["is_anomaly"] is False


def test_distribution_retains_mean_and_scale_ratio_signals():
    sparse_tail = detect_distribution([1.0] * 99 + [1000.0], [1.0] * 100)
    scale_shift = detect_distribution([-6, -3, 0, 3, 6] * 4, [-2, -1, 0, 1, 2] * 4)
    assert sparse_tail["is_anomaly"] is True
    assert scale_shift["is_anomaly"] is True


def test_distribution_ignores_individual_non_numeric_values():
    result = detect_distribution([20, "bad", 20, 20], [10, 10, "bad", 10])
    assert result["is_anomaly"] is True


def test_column_lineage_is_transitive_and_cycle_safe():
    graph = {"a": ["b"], "b": ["c"], "c": ["a", "d"]}
    assert column_downstream(graph, "a") == ["b", "c", "d"]


def test_manifest_parser_keeps_only_known_dbt_resources(tmp_path: Path):
    manifest = {
        "nodes": {"model.lab.stg_orders": {}, "model.lab.fct": {}},
        "sources": {},
        "child_map": {"model.lab.stg_orders": ["model.lab.fct", "external.node"]},
    }
    path = tmp_path / "manifest.json"
    path.write_text(__import__("json").dumps(manifest), encoding="utf-8")
    assert extract_dbt_dataset_graph(path) == {"model.lab.stg_orders": ["model.lab.fct"]}


def test_multiwindow_distinguishes_transient_and_sustained_burn():
    assert multiwindow_burn(20, 1)["page"] is False
    sustained = multiwindow_burn(20, 10)
    assert sustained["page"] is True and sustained["severity"] == "critical"
    with pytest.raises(ValueError):
        multiwindow_burn(-1, 1)


def test_embedding_norm_shift_detects_distribution_drift():
    result = rag_embedding_shift([0.5] * 8, [1.0, 1.01, 0.99, 1.02, 1.0, 1.01, 0.98, 1.02])
    assert result["is_anomaly"] is True
    assert result["method"].startswith("embedding_norm:")
