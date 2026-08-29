#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observability.anomaly import detect_anomaly
from observability.lineage import get_column_downstream, get_downstream_assets
from observability.rag_metrics import detect_text_length_shift
from observability.slo import calculate_slo
from src.contract_validator import failed_issues, load_contract, quarantine_rows, validate_dataframe
from src.io_utils import load_jsonl, load_yaml


def _action_summary(issues: list[dict]) -> dict[str, int]:
    summary: dict[str, int] = {"block": 0, "warn": 0, "quarantine": 0}
    for issue in failed_issues(issues):
        action = str(issue.get("action", "warn"))
        summary[action] = summary.get(action, 0) + 1
    return summary


def _failed_check(issues: list[dict], check: str) -> bool:
    return any(not issue["passed"] and issue["check"] == check for issue in issues)


def main() -> None:
    now = datetime.now(timezone.utc)
    orders = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    history = pd.read_csv(ROOT / "data" / "history" / "metrics_history.csv")
    order_issues = validate_dataframe(orders, load_contract(ROOT / "contracts" / "orders_contract.yaml"), now=now)
    order_failed = failed_issues(order_issues)
    critical_failed = failed_issues(order_issues, min_severity="critical")
    # The starter batch does not carry a trustworthy traffic-segment label. Do
    # not infer one from wall-clock weekday and turn a healthy 600-row fixture
    # into a Saturday false positive. Callers with real segment metadata pass
    # ``same_segment_history`` through the stable API.
    row_result = detect_anomaly(len(orders), history["row_count"].tail(28).tolist(), method="auto", context={"metric_name": "row_count"})
    updated = pd.to_datetime(orders["updated_at"], utc=True, errors="coerce", format="mixed")
    freshness_minutes = (pd.Timestamp(now) - updated.max()).total_seconds() / 60.0

    docs = load_jsonl(ROOT / "data" / "incoming" / "kb_documents.jsonl")
    kb_issues = validate_dataframe(pd.DataFrame(docs), load_contract(ROOT / "contracts" / "kb_contract.yaml"), now=now)
    kb_failed = failed_issues(kb_issues)
    text_result = detect_text_length_shift([doc.get("content", "") for doc in docs], history["mean_text_length"].tail(14).tolist())
    embedding_result = {"is_anomaly": False, "score": 0.0, "method": "not_available", "reason": "incoming documents contain no embedding norms"}
    contract_slo = calculate_slo(0.999, bad_events=1 if critical_failed else 0, total_events=1)
    lab_config = load_yaml(ROOT / "lab_config.yaml")
    freshness_slos = {
        "revenue_freshness": calculate_slo(
            float(lab_config["slo"]["revenue_freshness"]["target"]),
            bad_events=1 if _failed_check(order_issues, "freshness") else 0,
            total_events=1,
        ),
        "rag_index_freshness_proxy": calculate_slo(
            float(lab_config["slo"]["rag_index_freshness"]["target"]),
            bad_events=1 if _failed_check(kb_issues, "freshness") else 0,
            total_events=1,
        ),
    }

    lineage_payload = json.loads((ROOT / "data" / "baseline" / "lineage_graph.json").read_text(encoding="utf-8"))
    blast_radius = get_downstream_assets(lineage_payload["dataset_lineage"], "stg_orders")
    column_blast_radius = get_column_downstream(lineage_payload["column_lineage"], "raw_orders.amount")
    report = {
        "timestamp": now.isoformat(),
        "orders_rows": int(len(orders)),
        "failed_contract_checks": len(order_failed),
        "critical_contract_failures": len(critical_failed),
        "order_contract": {"failures": order_failed, "actions": _action_summary(order_issues), "quarantine_rows": int(len(quarantine_rows(orders, order_failed)))},
        "kb_contract": {"failed_checks": len(kb_failed), "failures": kb_failed, "actions": _action_summary(kb_issues)},
        "row_count_anomaly": row_result,
        "freshness_minutes": float(freshness_minutes),
        "kb_text_length_signal": text_result,
        "kb_embedding_norm_signal": embedding_result,
        "contract_slo": contract_slo,
        "freshness_slos": freshness_slos,
        "burn_windows": {"available": False, "reason": "a single baseline run has no short/long contract-quality windows"},
        "sample_blast_radius_from_stg_orders": blast_radius,
        "column_blast_radius_from_raw_orders_amount": column_blast_radius,
    }
    out = ROOT / "reports" / "latest_metrics.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("=== DATA RELIABILITY BASELINE ===")
    print(f"orders rows              : {len(orders)}")
    print(f"order contract failures  : {len(order_failed)} ({len(critical_failed)} critical)")
    print(f"KB contract failures     : {len(kb_failed)}")
    print(f"row-count anomaly        : {row_result['is_anomaly']} ({row_result['method']}, score={row_result['score']:.2f})")
    print(f"freshness minutes        : {freshness_minutes:.1f}")
    print(f"KB length anomaly        : {text_result['is_anomaly']}")
    print(f"revenue freshness SLO    : breached={freshness_slos['revenue_freshness']['breached']}")
    print(f"RAG freshness SLO        : breached={freshness_slos['rag_index_freshness_proxy']['breached']}")
    print(f"sample blast radius      : {', '.join(blast_radius)}")
    print(f"report                   : {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
