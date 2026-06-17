"""
Detector calibration.

Surveillance is fundamentally a calibration problem: every threshold trades
recall (catching real abuse) against precision (not drowning analysts in false
positives). Centralizing the thresholds here makes that calibration explicit and
reviewable instead of hiding magic numbers inside the detectors. Each value
carries the rationale a reviewer (or a regulator) would ask for.

In production these would be tuned per market against historical
true/false-positive rates and re-validated on a schedule; the values below are
illustrative defaults sized to this synthetic dataset.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class DetectorConfig:
    # --- spoofing -----------------------------------------------------------
    # An order counts as "large" only if it sits in the top tail of size; the
    # 95th percentile adapts to each dataset rather than fixing a raw quantity.
    spoof_large_qty_quantile: float = 0.95
    # Bona-fide orders rest; a place/cancel inside a few seconds with no fill is
    # the spoofing signature. 10s is conservative (fewer false positives).
    spoof_cancel_window_s: int = 10

    # --- settlement (marking-the-close) ------------------------------------
    # Resolution-window length to inspect for ramping into the close.
    settlement_close_window_s: int = 600
    # Minimum price move (cents) over that window to consider it a ramp. ~15c on
    # a 1-99 scale is a material, non-noise move for an event contract.
    settlement_ramp_threshold: int = 15
    # One account must drive at least this share of aggressive buy volume in the
    # window to be named the dominant ramper.
    settlement_dominance_share: float = 0.50

    # --- position limit -----------------------------------------------------
    # Contract position limit; net exposure beyond this is a hard breach.
    position_limit: int = 25000

    # --- statistical anomaly ------------------------------------------------
    # Per-market z-score cutoff. 4 sigma is intentionally strict: this is the
    # noisiest, lowest-severity detector, so we bias it toward precision.
    anomaly_z_threshold: float = 4.0

    # --- layering / order-to-trade ratio -----------------------------------
    # Minimum resting orders before a cancel ratio is meaningful (avoids firing
    # on accounts that placed one or two orders).
    layering_min_orders: int = 15
    # Cancel-to-(cancel+fill) ratio above which quoting looks non-bona-fide.
    layering_cancel_ratio: float = 0.80

    # --- insider timing (prediction-market-specific) -----------------------
    # Final pre-resolution window to inspect for dormant-account accumulation.
    insider_window_s: int = 1200
    # An account is "dormant" if it traded this market at most this many times
    # before the window opened.
    insider_dormant_max_prior: int = 1
    # Minimum net position built inside the window to flag (filters tiny dabbles).
    insider_min_position: int = 1500


DEFAULT_CONFIG = DetectorConfig()
