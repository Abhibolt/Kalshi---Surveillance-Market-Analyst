"""
Synthetic event-contract market data generator.

Models a Kalshi-style binary event market: YES contracts priced in cents
(1-99). Generates a clean baseline of trades and resting orders, then injects
known market-abuse patterns so the surveillance detectors can be validated
against ground truth.

Run:  python data/generate_synthetic_data.py
Output:  data/trades.csv, data/orders.csv, data/labels.csv
"""
from __future__ import annotations
import os
import random
import datetime as dt
import pandas as pd

RNG = random.Random(42)
START = dt.datetime(2026, 6, 1, 9, 30, 0)
MARKETS = ["PRES-2028-DEM", "FED-CUT-JUL26", "SP500-ABOVE-6000-JUN"]
ACCOUNTS = [f"ACCT{i:03d}" for i in range(1, 41)]


def _ts(seconds: int) -> dt.datetime:
    return START + dt.timedelta(seconds=seconds)


def _rand_price() -> int:
    return max(1, min(99, int(RNG.gauss(50, 12))))


def generate_baseline(n_trades: int = 4000):
    """Normal two-sided trading flow across markets."""
    trades, orders = [], []
    tid = oid = 0
    for s in range(n_trades):
        market = RNG.choice(MARKETS)
        buyer, seller = RNG.sample(ACCOUNTS, 2)
        price = _rand_price()
        qty = RNG.randint(1, 200)
        aggressor = RNG.choice(["buy", "sell"])
        tid += 1
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(s * 3),
            market_id=market, buyer=buyer, seller=seller,
            price=price, quantity=qty, aggressor_side=aggressor, label="clean",
        ))
        # a resting order for most trades (used by spoofing detector)
        oid += 1
        side = RNG.choice(["buy", "sell"])
        orders.append(dict(
            order_id=f"O{oid:06d}", timestamp=_ts(s * 3),
            market_id=market, account_id=RNG.choice(ACCOUNTS),
            side=side, price=_rand_price(), quantity=RNG.randint(1, 150),
            action=RNG.choices(["fill", "cancel"], weights=[0.7, 0.3])[0],
            label="clean",
        ))
    return trades, orders, tid, oid


def inject_wash_trades(trades, tid, n=12):
    """Self-matching: same beneficial owner on both sides (no economic risk transfer)."""
    labels = []
    linked = ("ACCT005", "ACCT006")  # known linked accounts (same owner)
    for k in range(n):
        market = RNG.choice(MARKETS)
        price = _rand_price()
        tid += 1
        a, b = (linked if k % 2 == 0 else (linked[0], linked[0]))
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(20000 + k * 5),
            market_id=market, buyer=a, seller=b,
            price=price, quantity=RNG.randint(300, 800),
            aggressor_side="buy", label="wash",
        ))
        labels.append(f"T{tid:06d}")
    return tid, labels


def inject_spoofing(orders, oid, n=8):
    """Large orders placed then canceled before execution, away from touch."""
    labels = []
    spoofer = "ACCT017"
    for k in range(n):
        market = RNG.choice(MARKETS)
        base = 40000 + k * 30
        # large order placed then canceled (spoof)
        oid += 1
        orders.append(dict(
            order_id=f"O{oid:06d}", timestamp=_ts(base),
            market_id=market, account_id=spoofer, side="buy",
            price=_rand_price(), quantity=RNG.randint(2000, 5000),
            action="place", label="spoof",
        ))
        labels.append(f"O{oid:06d}")
        oid += 1
        orders.append(dict(
            order_id=f"O{oid:06d}", timestamp=_ts(base + 3),
            market_id=market, account_id=spoofer, side="buy",
            price=_rand_price(), quantity=RNG.randint(2000, 5000),
            action="cancel", label="spoof",
        ))
        labels.append(f"O{oid:06d}")
    return oid, labels


def inject_settlement_ramp(trades, tid, n=10):
    """Marking-the-close: aggressive same-account buying in the final pre-resolution window."""
    labels = []
    ramper = "ACCT023"
    market = "FED-CUT-JUL26"
    close = 70000
    price = 55
    for k in range(n):
        tid += 1
        price = min(98, price + RNG.randint(2, 5))  # ramp price up into the close
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(close + k * 4),
            market_id=market, buyer=ramper, seller=RNG.choice(ACCOUNTS),
            price=price, quantity=RNG.randint(400, 900),
            aggressor_side="buy", label="settlement_ramp",
        ))
        labels.append(f"T{tid:06d}")
    return tid, labels


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    trades, orders, tid, oid = generate_baseline()
    tid, wash = inject_wash_trades(trades, tid)
    oid, spoof = inject_spoofing(orders, oid)
    tid, ramp = inject_settlement_ramp(trades, tid)

    tdf = pd.DataFrame(trades).sort_values("timestamp").reset_index(drop=True)
    odf = pd.DataFrame(orders).sort_values("timestamp").reset_index(drop=True)
    labels = pd.DataFrame(
        [(i, "wash") for i in wash]
        + [(i, "spoof") for i in spoof]
        + [(i, "settlement_ramp") for i in ramp],
        columns=["id", "abuse_type"],
    )
    tdf.to_csv(os.path.join(here, "trades.csv"), index=False)
    odf.to_csv(os.path.join(here, "orders.csv"), index=False)
    labels.to_csv(os.path.join(here, "labels.csv"), index=False)
    print(f"Wrote {len(tdf)} trades, {len(odf)} orders, {len(labels)} planted-abuse rows.")


if __name__ == "__main__":
    main()
