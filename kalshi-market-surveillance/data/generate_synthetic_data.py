"""
Synthetic event-contract market data generator.

Models a Kalshi-style binary event market: YES contracts priced in cents
(1-99). Generates a clean baseline of trades and resting orders, then injects
known market-abuse patterns so the surveillance detectors can be validated
against ground truth.

Every injected pattern is written to ``labels.csv`` with its abuse type, so the
runner can score each detector's precision *and* recall — not just recall. The
clean baseline is what makes precision (false-positive rate) measurable: any
alert pointing only at unlabeled rows is a false positive.

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

# The linked pair (shared beneficial owner) is reserved for the wash pattern so
# it never trades together in the clean baseline -- that keeps wash precision
# interpretable rather than mixing planted and accidental linked-account trades.
LINKED_PAIR = ("ACCT005", "ACCT006")
BASELINE_POOL = [a for a in ACCOUNTS if a not in LINKED_PAIR]

# Dedicated bad actors that do NOT appear in the clean baseline, so their abuse
# is cleanly attributable (and, for the insider pattern, genuinely "dormant").
ACCT_POSITION = "ACCT901"
ACCT_LAYERING = "ACCT902"
ACCT_INSIDER = "ACCT903"


def _ts(seconds: int) -> dt.datetime:
    return START + dt.timedelta(seconds=seconds)


def _rand_price() -> int:
    return max(1, min(99, int(RNG.gauss(50, 12))))


def _baseline_qty() -> int:
    """Mostly small two-sided size, with a thin natural tail.

    The tail is deliberate: it produces a handful of genuinely large *clean*
    trades so the z-score detector generates real false positives. That makes
    its precision < 1.0 and tells an honest story about statistical detectors
    (high recall, noisier) versus the structural ones.
    """
    if RNG.random() < 0.002:
        return RNG.randint(350, 600)        # natural large clean trade (FP source)
    return RNG.randint(1, 200)


def generate_baseline(n_trades: int = 4000):
    """Normal two-sided trading flow across markets."""
    trades, orders = [], []
    tid = oid = 0
    for s in range(n_trades):
        market = RNG.choice(MARKETS)
        buyer, seller = RNG.sample(BASELINE_POOL, 2)
        tid += 1
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(s * 3),
            market_id=market, buyer=buyer, seller=seller,
            price=_rand_price(), quantity=_baseline_qty(),
            aggressor_side=RNG.choice(["buy", "sell"]), label="clean",
        ))
        # a resting order for most trades (used by spoofing/layering detectors)
        oid += 1
        orders.append(dict(
            order_id=f"O{oid:06d}", timestamp=_ts(s * 3),
            market_id=market, account_id=RNG.choice(BASELINE_POOL),
            side=RNG.choice(["buy", "sell"]), price=_rand_price(),
            quantity=RNG.randint(1, 150),
            action=RNG.choices(["fill", "cancel"], weights=[0.7, 0.3])[0],
            label="clean",
        ))
    return trades, orders, tid, oid


def inject_wash_trades(trades, tid, n=12):
    """Self-matching: same beneficial owner on both sides (no risk transfer)."""
    labels = []
    for k in range(n):
        market = RNG.choice(MARKETS)
        tid += 1
        a, b = (LINKED_PAIR if k % 2 == 0 else (LINKED_PAIR[0], LINKED_PAIR[0]))
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(20000 + k * 5),
            market_id=market, buyer=a, seller=b,
            price=_rand_price(), quantity=RNG.randint(300, 800),
            aggressor_side="buy", label="wash",
        ))
        labels.append((f"T{tid:06d}", "wash"))
    return tid, labels


def inject_spoofing(orders, oid, n=8):
    """Large orders placed then canceled before execution, false depth."""
    labels = []
    spoofer = "ACCT017"
    for k in range(n):
        market = RNG.choice(MARKETS)
        base = 40000 + k * 30
        oid += 1
        orders.append(dict(
            order_id=f"O{oid:06d}", timestamp=_ts(base),
            market_id=market, account_id=spoofer, side="buy",
            price=_rand_price(), quantity=RNG.randint(2000, 5000),
            action="place", label="spoof",
        ))
        labels.append((f"O{oid:06d}", "spoof"))
        oid += 1
        orders.append(dict(
            order_id=f"O{oid:06d}", timestamp=_ts(base + 3),
            market_id=market, account_id=spoofer, side="buy",
            price=_rand_price(), quantity=RNG.randint(2000, 5000),
            action="cancel", label="spoof",
        ))
        labels.append((f"O{oid:06d}", "spoof"))
    return oid, labels


def inject_settlement_ramp(trades, tid, n=10):
    """Marking-the-close: aggressive same-account buying into resolution."""
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
            market_id=market, buyer=ramper, seller=RNG.choice(BASELINE_POOL),
            price=price, quantity=RNG.randint(400, 900),
            aggressor_side="buy", label="settlement_ramp",
        ))
        labels.append((f"T{tid:06d}", "settlement_ramp"))
    return tid, labels


def inject_position_breach(trades, tid, n=120):
    """One account accumulating a net long well beyond the position limit.

    Per-trade size is kept near the baseline (not an outlier) so the breach is
    detected by net-position aggregation, not by the size detector.
    """
    labels = []
    market = "SP500-ABOVE-6000-JUN"
    for k in range(n):
        tid += 1
        # Placed mid-session (not at the tape's end) so this is a clean
        # position-limit signal and not mistaken for pre-resolution accumulation.
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(5000 + k * 2),
            market_id=market, buyer=ACCT_POSITION, seller=RNG.choice(BASELINE_POOL),
            price=_rand_price(), quantity=RNG.randint(240, 290),
            aggressor_side="buy", label="position_breach",
        ))
        labels.append((f"T{tid:06d}", "position_breach"))
    return tid, labels


def inject_outliers(trades, tid, n=12):
    """Single trades whose size is a gross per-market statistical outlier.

    Sized well above the clean tail (so recall is reliable) but not so enormous
    that they swamp the per-market sigma -- otherwise the z-score goalpost would
    move out past the natural large-but-clean trades and hide the detector's real
    false-positive behaviour.
    """
    labels = []
    for k in range(n):
        market = RNG.choice(MARKETS)
        buyer, seller = RNG.sample(BASELINE_POOL, 2)
        tid += 1
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(45000 + k * 7),
            market_id=market, buyer=buyer, seller=seller,
            price=_rand_price(), quantity=RNG.randint(900, 1400),
            aggressor_side=RNG.choice(["buy", "sell"]), label="outlier",
        ))
        labels.append((f"T{tid:06d}", "outlier"))
    return tid, labels


def inject_layering(orders, oid, n=26):
    """Manipulative quoting: many resting orders entered then canceled.

    A high cancel-to-fill ratio with no genuine fills is the layering / excessive
    order-to-trade signature -- distinct from spoofing's single oversized order.
    """
    labels = []
    market = "PRES-2028-DEM"
    for k in range(n):
        oid += 1
        action = "fill" if k % 9 == 0 else "cancel"   # ~89% cancels, a few fills
        # Only the canceled (non-bona-fide) orders are the abuse; the genuine
        # fills are clean and are not part of the ground-truth label set.
        label = "clean" if action == "fill" else "layering"
        orders.append(dict(
            order_id=f"O{oid:06d}", timestamp=_ts(60000 + k * 8),
            market_id=market, account_id=ACCT_LAYERING, side=RNG.choice(["buy", "sell"]),
            price=_rand_price(), quantity=RNG.randint(80, 200), action=action,
            label=label,
        ))
        if label == "layering":
            labels.append((f"O{oid:06d}", "layering"))
    return oid, labels


def inject_insider_timing(trades, tid, n=14):
    """Prediction-market-specific: a previously-dormant account building a large
    aggressive position in the final pre-resolution window.

    In event contracts the manipulable thing is often the real-world *outcome*:
    an account with non-public knowledge of the resolution loads up just before
    the event settles. The price drift here is kept under the marking-the-close
    threshold so this is caught by the dormancy+position logic, not the
    settlement detector.
    """
    labels = []
    market = "PRES-2028-DEM"
    price = 50
    for k in range(n):
        tid += 1
        price = min(64, price + 1)  # gentle drift (< marking-the-close threshold)
        trades.append(dict(
            trade_id=f"T{tid:06d}", timestamp=_ts(79000 + k * 30),
            market_id=market, buyer=ACCT_INSIDER, seller=RNG.choice(BASELINE_POOL),
            price=price, quantity=RNG.randint(240, 300),
            aggressor_side="buy", label="insider",
        ))
        labels.append((f"T{tid:06d}", "insider"))
    return tid, labels


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    trades, orders, tid, oid = generate_baseline()

    all_labels = []
    tid, lab = inject_wash_trades(trades, tid);        all_labels += lab
    oid, lab = inject_spoofing(orders, oid);           all_labels += lab
    tid, lab = inject_settlement_ramp(trades, tid);    all_labels += lab
    tid, lab = inject_position_breach(trades, tid);    all_labels += lab
    tid, lab = inject_outliers(trades, tid);           all_labels += lab
    oid, lab = inject_layering(orders, oid);           all_labels += lab
    tid, lab = inject_insider_timing(trades, tid);     all_labels += lab

    tdf = pd.DataFrame(trades).sort_values("timestamp").reset_index(drop=True)
    odf = pd.DataFrame(orders).sort_values("timestamp").reset_index(drop=True)
    labels = pd.DataFrame(all_labels, columns=["id", "abuse_type"])

    tdf.to_csv(os.path.join(here, "trades.csv"), index=False)
    odf.to_csv(os.path.join(here, "orders.csv"), index=False)
    labels.to_csv(os.path.join(here, "labels.csv"), index=False)

    by_type = labels.groupby("abuse_type").size().to_dict()
    print(f"Wrote {len(tdf)} trades, {len(odf)} orders.")
    print(f"Planted abuse rows by type: {by_type}")


if __name__ == "__main__":
    main()
