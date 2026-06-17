"""
Detector scoring against labeled ground truth.

A surveillance program lives or dies on the precision/recall tradeoff: recall is
how much real abuse you catch, precision is how few false positives you put in
front of an analyst. Reporting recall alone (the common demo shortcut) hides the
alert-fatigue cost that is the hard part of the job. This module scores both.

Conventions:
  * An alert is a TRUE POSITIVE if any of its evidence IDs point at a planted
    (labeled) abuse row -- regardless of typology, because flagging genuine abuse
    is never a false alarm even if attributed to a neighbouring pattern.
  * An alert is a FALSE POSITIVE if every evidence ID it cites is an unlabeled
    (clean) row.
  * Recall is measured per detector against the abuse type it targets: of that
    type's planted IDs, how many appear in the detector's alerts.
"""
from __future__ import annotations
import pandas as pd

# Which planted abuse type each detector is primarily responsible for catching.
DETECTOR_TARGET = {
    "wash_trade": "wash",
    "spoofing": "spoof",
    "settlement_manipulation": "settlement_ramp",
    "position_limit": "position_breach",
    "statistical_anomaly": "outlier",
    "layering": "layering",
    "insider_timing": "insider",
}

SCORE_COLS = ["detector", "alerts", "tp", "fp", "precision",
              "planted", "caught", "recall", "f1"]


def _ids(evidence: str) -> set:
    """Split an evidence_ids cell into individual source IDs."""
    return set(str(evidence).replace("|", " ").split())


def score(alerts: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Return a per-detector scorecard with precision, recall and F1."""
    planted_all = set(labels["id"])
    planted_by_type = {
        t: set(g["id"]) for t, g in labels.groupby("abuse_type")
    }

    rows = []
    for detector, target in DETECTOR_TARGET.items():
        d_alerts = alerts[alerts["detector"] == detector] if not alerts.empty else alerts
        truth = planted_by_type.get(target, set())

        tp = fp = 0
        caught = set()
        for ev in (d_alerts["evidence_ids"] if len(d_alerts) else []):
            ev_ids = _ids(ev)
            if ev_ids & planted_all:
                tp += 1
            else:
                fp += 1
            caught |= (ev_ids & truth)

        n_alerts = int(len(d_alerts))
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = len(caught) / len(truth) if truth else float("nan")
        if precision == precision and recall == recall and (precision + recall):
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = float("nan")

        rows.append(dict(
            detector=detector, alerts=n_alerts, tp=tp, fp=fp,
            precision=precision, planted=len(truth), caught=len(caught),
            recall=recall, f1=f1,
        ))
    return pd.DataFrame(rows, columns=SCORE_COLS)


def _fmt(x: float) -> str:
    return "  n/a" if x != x else f"{x:5.2f}"   # x != x is True for NaN


def format_scorecard(scorecard: pd.DataFrame) -> str:
    lines = ["Detector scorecard (precision = alert quality, recall = coverage):"]
    lines.append(f"  {'detector':<24}{'alerts':>7}{'TP':>5}{'FP':>5}"
                 f"{'prec':>7}{'planted':>9}{'caught':>8}{'recall':>8}{'F1':>7}")
    for _, r in scorecard.iterrows():
        lines.append(
            f"  {r['detector']:<24}{r['alerts']:>7}{r['tp']:>5}{r['fp']:>5}"
            f"{_fmt(r['precision']):>7}{r['planted']:>9}{r['caught']:>8}"
            f"{_fmt(r['recall']):>8}{_fmt(r['f1']):>7}"
        )
    return "\n".join(lines)
