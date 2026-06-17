#!/usr/bin/env python3
"""
CLI entry point.

    python run_surveillance.py            # uses data/*.csv, writes output/alerts.csv
    python run_surveillance.py --validate # also scores detector recall vs data/labels.csv
"""
import argparse
import os
import pandas as pd

from surveillance.runner import run_surveillance, summarize
from surveillance.metrics import score, format_scorecard

HERE = os.path.dirname(os.path.abspath(__file__))
# Known intelligence input: ACCT005 / ACCT006 share a beneficial owner.
LINKED = {("ACCT005", "ACCT006")}


def _load(name):
    return pd.read_csv(os.path.join(HERE, "data", name))


def validate(alerts: pd.DataFrame):
    labels = _load("labels.csv")
    scorecard = score(alerts, labels)
    print("\n" + format_scorecard(scorecard))


def main():
    ap = argparse.ArgumentParser(description="Event-market surveillance runner")
    ap.add_argument("--validate", action="store_true", help="score recall vs labels.csv")
    args = ap.parse_args()

    trades = _load("trades.csv")
    orders = _load("orders.csv")
    alerts = run_surveillance(trades, orders, linked_accounts=LINKED)

    out_dir = os.path.join(HERE, "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "alerts.csv")
    alerts.to_csv(out_path, index=False)

    print(summarize(alerts))
    print(f"\nWrote {len(alerts)} alerts -> {out_path}")
    if args.validate:
        validate(alerts)


if __name__ == "__main__":
    main()
