"""Event-market surveillance toolkit."""
from .detectors import (
    detect_wash_trades,
    detect_spoofing,
    detect_settlement_manipulation,
    detect_position_limit_breaches,
    detect_statistical_anomalies,
)
from .runner import run_surveillance, Alert

__all__ = [
    "detect_wash_trades",
    "detect_spoofing",
    "detect_settlement_manipulation",
    "detect_position_limit_breaches",
    "detect_statistical_anomalies",
    "run_surveillance",
    "Alert",
]
