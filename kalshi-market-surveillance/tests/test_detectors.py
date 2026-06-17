"""Unit tests: each detector must catch its planted pattern and stay quiet on clean data."""
import pandas as pd
import pytest

from surveillance.detectors import (
    detect_wash_trades,
    detect_spoofing,
    detect_settlement_manipulation,
    detect_position_limit_breaches,
    detect_statistical_anomalies,
    detect_layering,
    detect_insider_timing,
)
from surveillance.metrics import score


def _trade(tid, market, buyer, seller, price, qty, ts="2026-06-01 09:30:00", agg="buy"):
    return dict(trade_id=tid, timestamp=ts, market_id=market, buyer=buyer,
                seller=seller, price=price, quantity=qty, aggressor_side=agg)


def test_wash_self_match():
    df = pd.DataFrame([_trade("T1", "M", "A", "A", 50, 100)])
    out = detect_wash_trades(df)
    assert len(out) == 1 and out.iloc[0]["detector"] == "wash_trade"


def test_wash_linked_accounts():
    df = pd.DataFrame([_trade("T1", "M", "A", "B", 50, 100)])
    out = detect_wash_trades(df, linked_accounts={("A", "B")})
    assert len(out) == 1


def test_wash_ignores_clean():
    df = pd.DataFrame([_trade("T1", "M", "A", "B", 50, 100)])
    assert detect_wash_trades(df).empty


def test_spoofing_place_then_cancel():
    orders = pd.DataFrame([
        dict(order_id="O1", timestamp="2026-06-01 09:30:00", market_id="M",
             account_id="X", side="buy", quantity=5000, action="place"),
        dict(order_id="O2", timestamp="2026-06-01 09:30:03", market_id="M",
             account_id="X", side="buy", quantity=5000, action="cancel"),
        dict(order_id="O3", timestamp="2026-06-01 09:30:00", market_id="M",
             account_id="Y", side="buy", quantity=10, action="fill"),
    ])
    out = detect_spoofing(orders, large_qty_quantile=0.5)
    assert len(out) == 1 and out.iloc[0]["account_id"] == "X"


def test_settlement_ramp():
    rows = []
    for i in range(10):
        rows.append(_trade(f"T{i}", "M", "RAMP", "S", 50 + i * 4, 500,
                           ts=f"2026-06-01 16:0{i}:00"))
    out = detect_settlement_manipulation(pd.DataFrame(rows), ramp_threshold=15)
    assert len(out) == 1 and out.iloc[0]["account_id"] == "RAMP"


def test_position_limit():
    df = pd.DataFrame([_trade("T1", "M", "BIG", "S", 50, 30000)])
    out = detect_position_limit_breaches(df, position_limit=25000)
    # both counterparties hold a position that breaches the limit
    assert "BIG" in set(out["account_id"]) and len(out) == 2


def test_statistical_anomaly():
    rows = [_trade(f"T{i}", "M", "A", "B", 50, 100) for i in range(50)]
    rows.append(_trade("BIG", "M", "A", "B", 50, 9999))
    out = detect_statistical_anomalies(pd.DataFrame(rows), z_threshold=4.0)
    assert "BIG" in set(out["evidence_ids"])


def _order(oid, acct, action, market="M", side="buy", qty=100,
           ts="2026-06-01 09:30:00"):
    return dict(order_id=oid, timestamp=ts, market_id=market, account_id=acct,
                side=side, price=50, quantity=qty, action=action)


def test_layering_high_cancel_ratio():
    orders = [_order(f"O{i}", "LAY", "cancel") for i in range(18)]
    orders += [_order(f"F{i}", "LAY", "fill") for i in range(2)]
    out = detect_layering(pd.DataFrame(orders), min_orders=15, cancel_ratio_threshold=0.80)
    assert len(out) == 1 and out.iloc[0]["account_id"] == "LAY"


def test_layering_ignores_balanced_quoting():
    orders = [_order(f"O{i}", "MM", "cancel") for i in range(10)]
    orders += [_order(f"F{i}", "MM", "fill") for i in range(10)]
    assert detect_layering(pd.DataFrame(orders), cancel_ratio_threshold=0.80).empty


def test_insider_timing_dormant_accumulation():
    rows = []
    # established account trades throughout the day (not dormant)
    for i in range(8):
        rows.append(_trade(f"E{i}", "M", "OLD", "S", 50, 100,
                           ts=f"2026-06-01 10:0{i}:00"))
    # dormant account loads up in the final window before resolution
    for i in range(6):
        rows.append(_trade(f"I{i}", "M", "GHOST", "S", 55, 400,
                           ts=f"2026-06-01 15:5{i}:00"))
    out = detect_insider_timing(pd.DataFrame(rows), window_s=1200,
                                dormant_max_prior=1, min_position=1500)
    assert len(out) == 1 and out.iloc[0]["account_id"] == "GHOST"


def test_insider_timing_ignores_established_account():
    rows = []
    # OLD has a long established presence well before the resolution window...
    for i in range(10):
        rows.append(_trade(f"P{i}", "M", "OLD", "S", 50, 400,
                           ts=f"2026-06-01 10:0{i}:00"))
    # ...and also trades inside the final window. Not dormant -> no flag.
    for i in range(4):
        rows.append(_trade(f"W{i}", "M", "OLD", "S", 55, 400,
                           ts=f"2026-06-01 15:5{i}:00"))
    assert detect_insider_timing(pd.DataFrame(rows), window_s=1200,
                                 dormant_max_prior=1, min_position=1500).empty


def test_metrics_precision_and_recall():
    alerts = pd.DataFrame([
        dict(detector="wash_trade", severity="high", market_id="M",
             account_id="A", detail="", evidence_ids="W1"),       # true positive
        dict(detector="wash_trade", severity="high", market_id="M",
             account_id="A", detail="", evidence_ids="C1"),       # false positive (clean)
    ])
    labels = pd.DataFrame([("W1", "wash"), ("W2", "wash")], columns=["id", "abuse_type"])
    sc = score(alerts, labels).set_index("detector").loc["wash_trade"]
    assert sc["tp"] == 1 and sc["fp"] == 1
    assert sc["precision"] == 0.5     # 1 of 2 alerts genuine
    assert sc["recall"] == 0.5        # caught 1 of 2 planted wash ids


def test_empty_inputs_safe():
    empty = pd.DataFrame(columns=["trade_id", "timestamp", "market_id", "buyer",
                                   "seller", "price", "quantity", "aggressor_side"])
    assert detect_wash_trades(empty).empty
    assert detect_settlement_manipulation(empty).empty
    assert detect_position_limit_breaches(empty).empty
    assert detect_statistical_anomalies(empty).empty
    assert detect_insider_timing(empty).empty
    assert detect_layering(pd.DataFrame(columns=["order_id", "account_id",
                                                 "market_id", "action"])).empty
