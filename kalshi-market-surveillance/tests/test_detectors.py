"""Unit tests: each detector must catch its planted pattern and stay quiet on clean data."""
import pandas as pd
import pytest

from surveillance.detectors import (
    detect_wash_trades,
    detect_spoofing,
    detect_settlement_manipulation,
    detect_position_limit_breaches,
    detect_statistical_anomalies,
)


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


def test_empty_inputs_safe():
    empty = pd.DataFrame(columns=["trade_id", "timestamp", "market_id", "buyer",
                                   "seller", "price", "quantity", "aggressor_side"])
    assert detect_wash_trades(empty).empty
    assert detect_settlement_manipulation(empty).empty
    assert detect_position_limit_breaches(empty).empty
    assert detect_statistical_anomalies(empty).empty
