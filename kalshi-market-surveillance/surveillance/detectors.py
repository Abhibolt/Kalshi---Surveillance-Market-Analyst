"""
Market-abuse detectors for binary event contracts.

Each detector takes a pandas DataFrame and returns a DataFrame of alerts with a
consistent schema: [detector, severity, market_id, account_id, detail, evidence_ids].
The logic mirrors the abuse categories named in exchange/CFTC market-integrity
rules: wash trading, spoofing/layering, settlement (marking-the-close)
manipulation, position-limit breaches, and statistical outliers.
"""
from __future__ import annotations
from typing import Optional, Set, Tuple
import pandas as pd

ALERT_COLS = ["detector", "severity", "market_id", "account_id", "detail", "evidence_ids"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=ALERT_COLS)


def detect_wash_trades(
    trades: pd.DataFrame,
    linked_accounts: Optional[Set[Tuple[str, str]]] = None,
) -> pd.DataFrame:
    """Flag trades with no genuine transfer of beneficial ownership.

    Catches (a) self-matches where buyer == seller, and (b) trades between
    accounts known to share a beneficial owner (``linked_accounts``).
    """
    linked = set()
    for pair in (linked_accounts or set()):
        linked.add(tuple(sorted(pair)))

    rows = []
    for _, t in trades.iterrows():
        pair = tuple(sorted((t["buyer"], t["seller"])))
        self_match = t["buyer"] == t["seller"]
        linked_match = pair in linked
        if self_match or linked_match:
            rows.append(dict(
                detector="wash_trade",
                severity="high",
                market_id=t["market_id"],
                account_id=t["buyer"],
                detail=("self-match (same account both sides)" if self_match
                        else f"trade between linked accounts {pair}"),
                evidence_ids=t["trade_id"],
            ))
    return pd.DataFrame(rows, columns=ALERT_COLS) if rows else _empty()


def detect_spoofing(
    orders: pd.DataFrame,
    large_qty_quantile: float = 0.95,
    cancel_window_s: int = 10,
) -> pd.DataFrame:
    """Flag large orders placed and then canceled within a short window.

    Spoofing = entering large non-bona-fide orders to create false depth, then
    canceling before execution. We look for a place/cancel pair on the same
    (account, market, side) for an order whose size is in the top tail.
    """
    if orders.empty or "action" not in orders:
        return _empty()
    o = orders.copy()
    o["timestamp"] = pd.to_datetime(o["timestamp"])
    threshold = o["quantity"].quantile(large_qty_quantile)

    rows = []
    for (acct, market, side), grp in o.groupby(["account_id", "market_id", "side"]):
        grp = grp.sort_values("timestamp")
        places = grp[(grp["action"] == "place") & (grp["quantity"] >= threshold)]
        cancels = grp[grp["action"] == "cancel"]
        for _, p in places.iterrows():
            window = cancels[
                (cancels["timestamp"] >= p["timestamp"])
                & (cancels["timestamp"] <= p["timestamp"] + pd.Timedelta(seconds=cancel_window_s))
            ]
            if not window.empty:
                c = window.iloc[0]
                rows.append(dict(
                    detector="spoofing",
                    severity="high",
                    market_id=market,
                    account_id=acct,
                    detail=f"large {side} order qty={int(p['quantity'])} canceled within "
                           f"{cancel_window_s}s (no execution)",
                    evidence_ids=f"{p['order_id']}|{c['order_id']}",
                ))
    return pd.DataFrame(rows, columns=ALERT_COLS) if rows else _empty()


def detect_settlement_manipulation(
    trades: pd.DataFrame,
    close_window_s: int = 600,
    ramp_threshold: int = 15,
) -> pd.DataFrame:
    """Flag 'marking-the-close': one account driving price into the resolution window.

    For each market we take the final ``close_window_s`` of activity and flag any
    account whose net aggressive buying moves the print by more than
    ``ramp_threshold`` cents over that window.
    """
    if trades.empty:
        return _empty()
    t = trades.copy()
    t["timestamp"] = pd.to_datetime(t["timestamp"])
    rows = []
    for market, grp in t.groupby("market_id"):
        grp = grp.sort_values("timestamp")
        close = grp["timestamp"].max()
        window = grp[grp["timestamp"] >= close - pd.Timedelta(seconds=close_window_s)]
        if len(window) < 3:
            continue
        move = window["price"].iloc[-1] - window["price"].iloc[0]
        if abs(move) < ramp_threshold:
            continue
        # which account dominates aggressive flow in the window?
        agg = window[window["aggressor_side"] == "buy"]
        if agg.empty:
            continue
        dominant = agg.groupby("buyer")["quantity"].sum().idxmax()
        share = agg.groupby("buyer")["quantity"].sum().max() / agg["quantity"].sum()
        if share >= 0.5:
            rows.append(dict(
                detector="settlement_manipulation",
                severity="critical",
                market_id=market,
                account_id=dominant,
                detail=f"price moved {move:+d}c into close; {dominant} = "
                       f"{share:.0%} of aggressive buy volume in final {close_window_s}s",
                evidence_ids="|".join(window["trade_id"].tolist()[:20]),
            ))
    return pd.DataFrame(rows, columns=ALERT_COLS) if rows else _empty()


def detect_position_limit_breaches(
    trades: pd.DataFrame,
    position_limit: int = 25000,
) -> pd.DataFrame:
    """Flag accounts whose net position in a market exceeds the contract limit."""
    if trades.empty:
        return _empty()
    longs = trades.groupby(["buyer", "market_id"])["quantity"].sum()
    longs.index = longs.index.set_names(["account", "market_id"])
    shorts = trades.groupby(["seller", "market_id"])["quantity"].sum()
    shorts.index = shorts.index.set_names(["account", "market_id"])
    net = longs.subtract(shorts, fill_value=0)
    rows = []
    for (acct, market), pos in net.items():
        if abs(pos) > position_limit:
            rows.append(dict(
                detector="position_limit",
                severity="medium",
                market_id=market,
                account_id=acct,
                detail=f"net position {int(pos):+d} exceeds limit {position_limit}",
                evidence_ids=f"{acct}:{market}",
            ))
    return pd.DataFrame(rows, columns=ALERT_COLS) if rows else _empty()


def detect_statistical_anomalies(
    trades: pd.DataFrame,
    z_threshold: float = 4.0,
) -> pd.DataFrame:
    """Flag trades whose size is a per-market statistical outlier (z-score)."""
    if trades.empty:
        return _empty()
    rows = []
    for market, grp in trades.groupby("market_id"):
        mu, sigma = grp["quantity"].mean(), grp["quantity"].std(ddof=0)
        if not sigma or pd.isna(sigma):
            continue
        grp = grp.assign(z=(grp["quantity"] - mu) / sigma)
        for _, t in grp[grp["z"].abs() >= z_threshold].iterrows():
            rows.append(dict(
                detector="statistical_anomaly",
                severity="low",
                market_id=market,
                account_id=t["buyer"],
                detail=f"trade qty {int(t['quantity'])} is {t['z']:.1f}σ from market mean",
                evidence_ids=t["trade_id"],
            ))
    return pd.DataFrame(rows, columns=ALERT_COLS) if rows else _empty()
