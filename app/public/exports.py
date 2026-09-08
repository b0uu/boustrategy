"""Versioned exports consume the same approved snapshot as decision detail."""

import csv
import io
from typing import Any


def decision_csv(item: dict[str, Any]) -> str:
    execution = item.get("execution") or {}
    values = {
        "export_version": "public-decision-csv-1",
        "public_id": item["public_id"],
        "portfolio_id": item["portfolio_id"],
        "created_at": item["created_at"],
        "ticker": item["ticker"],
        "company_name": item.get("company_name"),
        "decision": item["decision"],
        "public_summary": item["public_summary"],
        "policy_outcome": item["policy_outcome"],
        "lifecycle": item["lifecycle"],
        "proposed_target_weight": item.get("proposed_target_weight"),
        "final_target_weight": item.get("final_target_weight"),
        "current_weight": item.get("current_weight"),
        "sized_notional": (item.get("sized_order") or {}).get("notional"),
        "requested_notional": (item.get("requested_order") or {}).get("notional"),
        "confirmed_quantity": execution.get("quantity"),
        "confirmed_gross_notional": execution.get("gross_notional"),
        "confirmed_fees": execution.get("fees"),
    }
    for key, value in values.items():
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            values[key] = "'" + value
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(values))
    writer.writeheader()
    writer.writerow(values)
    return output.getvalue()
