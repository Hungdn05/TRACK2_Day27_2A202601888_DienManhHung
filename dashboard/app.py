from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "latest_metrics.json"
HISTORY = ROOT / "data" / "history" / "metrics_history.csv"

st.set_page_config(page_title="Data Reliability Lab", layout="wide")
st.title("Data Reliability Game Day")
st.caption("Starter dashboard - improve it only if it helps incident decisions.")

if not REPORT.exists():
    st.warning("Run `make baseline` first to generate reports/latest_metrics.json")
    st.stop()

report = json.loads(REPORT.read_text(encoding="utf-8"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Orders rows", report["orders_rows"])
c2.metric("Freshness (min)", f"{report['freshness_minutes']:.1f}")
c3.metric("Contract failures", report["failed_contract_checks"])
c4.metric("Critical failures", report["critical_contract_failures"])

st.subheader("Current signals")
st.json({
    "row_count_anomaly": report["row_count_anomaly"],
    "kb_text_length_signal": report["kb_text_length_signal"],
    "contract_slo": report["contract_slo"],
    "freshness_slos": report.get("freshness_slos", {}),
    "kb_contract": report.get("kb_contract", {}),
    "burn_windows": report.get("burn_windows", {}),
})

slo = report["contract_slo"]
c5, c6, c7 = st.columns(3)
c5.metric("SLO target", f"{slo['target']:.2%}")
c6.metric("Error budget remaining", f"{slo['remaining_error_budget_fraction']:.1%}")
c7.metric("Contract action", "BLOCK" if report["critical_contract_failures"] else "HEALTHY")

st.subheader("Actions and incident context")
st.json({
    "order_actions": report.get("order_contract", {}).get("actions", {}),
    "quarantine_rows": report.get("order_contract", {}).get("quarantine_rows", 0),
    "burn_windows": report.get("burn_windows", {}),
    "incident_status": "Awaiting mystery incident dataset / evidence",
})

st.subheader("Freshness SLOs")
st.json(report.get("freshness_slos", {}))

history = pd.read_csv(HISTORY)
st.subheader("Historical row count")
st.line_chart(history.set_index("date")[["row_count"]])

st.subheader("Example blast radius")
st.write("stg_orders -> " + " -> ".join(report["sample_blast_radius_from_stg_orders"]))
st.write("raw_orders.amount -> " + " -> ".join(report.get("column_blast_radius_from_raw_orders_amount", [])))
