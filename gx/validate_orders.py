#!/usr/bin/env python3
"""Run an Orders GX Suite, Validation Definition, Checkpoint and local action."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

import pandas as pd
import great_expectations as gx
from great_expectations.checkpoint import ActionContext, CheckpointResult, ValidationAction
from typing_extensions import override

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.contract_validator import failed_issues, load_contract, quarantine_rows, validate_dataframe


class WriteValidationEvidenceAction(ValidationAction):
    """A local, credential-free GX Action suitable for the classroom lab."""

    type: Literal["write_validation_evidence"] = "write_validation_evidence"
    output_path: str

    @override
    def run(
        self,
        checkpoint_result: CheckpointResult,
        action_context: ActionContext | None = None,
    ) -> dict:
        path = Path(self.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = checkpoint_result.describe()
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return {"evidence_path": str(path), "checkpoint_success": bool(checkpoint_result.success)}


def build_checkpoint(df: pd.DataFrame) -> tuple[gx.Checkpoint, dict[str, object]]:
    context = gx.get_context(mode="ephemeral")
    datasource = context.data_sources.add_pandas("orders_pandas")
    asset = datasource.add_dataframe_asset(name="orders_dataframe")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_orders")

    suite = gx.ExpectationSuite(name="orders_contract_suite")
    expectations = [
        gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToBeUnique(column="order_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="customer_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToBeBetween(column="amount", min_value=0, severity="critical"),
        gx.expectations.ExpectColumnValuesToBeInSet(column="currency", value_set=["USD", "VND"], severity="critical"),
        gx.expectations.ExpectColumnValuesToBeInSet(column="status", value_set=["pending", "completed", "refunded", "cancelled"], severity="warning"),
    ]
    for expectation in expectations:
        suite.add_expectation(expectation)
    context.suites.add(suite)
    validation_definition = gx.ValidationDefinition(
        name="orders_contract_validation",
        data=batch_definition,
        suite=suite,
    )
    context.validation_definitions.add(validation_definition)
    checkpoint = gx.Checkpoint(
        name="orders_contract_checkpoint",
        validation_definitions=[validation_definition],
        actions=[WriteValidationEvidenceAction(name="write_validation_evidence", output_path=str(ROOT / "reports" / "runtime" / "gx_validation.json"))],
        result_format={"result_format": "COMPLETE"},
    )
    context.checkpoints.add(checkpoint)
    return checkpoint, {"dataframe": df}


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    checkpoint, batch_parameters = build_checkpoint(df)
    checkpoint_result = checkpoint.run(batch_parameters=batch_parameters)

    contract_issues = validate_dataframe(df, load_contract(ROOT / "contracts" / "orders_contract.yaml"))
    failures = failed_issues(contract_issues)
    quarantined = quarantine_rows(df, failures)
    quarantine_path = ROOT / "data" / "quarantine" / "orders.csv"
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantined.to_csv(quarantine_path, index=False)

    severity_counts = {
        severity: len([issue for issue in failures if issue["severity"] == severity])
        for severity in ("critical", "warning", "info")
    }
    print("GX checkpoint:", "PASS" if checkpoint_result.success else "FAIL")
    print("Contract failures:", severity_counts)
    print(f"Quarantined rows: {len(quarantined)} -> {quarantine_path.relative_to(ROOT)}")
    print("Evidence:", "reports/runtime/gx_validation.json")

    critical_failures = failed_issues(contract_issues, min_severity="critical")
    raise SystemExit(0 if checkpoint_result.success and not critical_failures else 1)


if __name__ == "__main__":
    main()
