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

HERE = os.path.dirname(os.path.abspath(__file__))
# Known intelligence input: ACCT005 / ACCT006 share a beneficial owner.
LINKED = {("ACCT005", "ACCT006")}


def _load(name):
    return pd.read_csv(os.path.join(HERE, "data", name))


def validate(alerts: pd.DataFrame):
    labels = _load("labels.csv")
    flagged = set()
    for ids in alerts["evidence_ids"].astype(str):
        for part in ids.replace("|", " ").split():
            flagged.add(part)
    print("\nDetection recall vs. planted abuse (ground truth):")
    for abuse, grp in labels.groupby("abuse_type"):
        truth = set(grp["id"])
        hit = len(truth & flagged)
        print(f"  {abuse:<18} caught {hit}/{len(truth)} planted ids")


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
