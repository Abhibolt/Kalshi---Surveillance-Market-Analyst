"""
Surveillance runner: ingests trade/order data, applies every detector, and
emits a consolidated, severity-ranked alert blotter — the kind of daily
exception report a surveillance/controls analyst reviews and escalates from.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Set, Tuple
import pandas as pd

from .detectors import (
    detect_wash_trades,
    detect_spoofing,
    detect_settlement_manipulation,
    detect_position_limit_breaches,
    detect_statistical_anomalies,
)

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Alert:
    detector: str
    severity: str
    market_id: str
    account_id: str
    detail: str
    evidence_ids: str


def run_surveillance(
    trades: pd.DataFrame,
    orders: Optional[pd.DataFrame] = None,
    linked_accounts: Optional[Set[Tuple[str, str]]] = None,
    position_limit: int = 25000,
) -> pd.DataFrame:
    """Run all detectors and return one severity-ranked alert blotter."""
    frames = [
        detect_wash_trades(trades, linked_accounts=linked_accounts),
        detect_settlement_manipulation(trades),
        detect_position_limit_breaches(trades, position_limit=position_limit),
        detect_statistical_anomalies(trades),
    ]
    if orders is not None:
        frames.append(detect_spoofing(orders))

    alerts = pd.concat(frames, ignore_index=True)
    if alerts.empty:
        return alerts
    alerts["_rank"] = alerts["severity"].map(SEVERITY_RANK).fillna(9)
    alerts = (
        alerts.sort_values(["_rank", "detector"])
        .drop(columns="_rank")
        .reset_index(drop=True)
    )
    return alerts


def summarize(alerts: pd.DataFrame) -> str:
    if alerts.empty:
        return "No surveillance alerts generated."
    lines = ["Alert summary by detector / severity:"]
    counts = alerts.groupby(["severity", "detector"]).size()
    for (sev, det), n in counts.items():
        lines.append(f"  [{sev:>8}] {det:<26} {n}")
    lines.append(f"Total alerts: {len(alerts)}")
    return "\n".join(lines)
