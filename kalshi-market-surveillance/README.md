# Event-Market Surveillance Engine

A compact, production-style **market-abuse surveillance toolkit for binary event
contracts** (Kalshi-style prediction markets). It ingests trade and order data,
runs a battery of detectors aligned to exchange / CFTC market-integrity rules,
and emits a severity-ranked alert blotter — the daily exception report a
surveillance or operations-risk analyst reviews and escalates from.

Built to demonstrate that I *build* surveillance tooling, not just operate it.

## What it detects

| Detector | Abuse category | Logic |
|---|---|---|
| `wash_trade` | Wash trading / self-match | Buyer == seller, or trade between accounts with a shared beneficial owner (no genuine risk transfer). |
| `spoofing` | Spoofing | A single large order placed then canceled within a short window without execution — false depth. |
| `layering` | Layering / order-to-trade ratio | An account whose resting orders are overwhelmingly canceled rather than filled (non-bona-fide quoting). |
| `settlement_manipulation` | Marking-the-close | One account dominating aggressive flow and ramping the print into the resolution window. |
| `position_limit` | Limit breach | Net position in a market exceeding the contract position limit. |
| `statistical_anomaly` | Outlier flow | Trade size that is a per-market statistical outlier (z-score). |
| `insider_timing` | Insider trading on resolution | A previously-dormant account building a large aggressive position in the final pre-resolution window — a prediction-market-specific typology where the manipulable thing is the real-world outcome. |

Threshold rationale, regulatory-typology mapping, and known false-positive
sources for every detector are documented in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Quick start

```bash
pip install -r requirements.txt
python data/generate_synthetic_data.py     # build labeled synthetic data
python run_surveillance.py --validate       # run detectors + score precision/recall vs ground truth
pytest -q                                   # run the test suite
```

## Example output

```
Alert summary by detector / severity:
  [critical] insider_timing             1
  [critical] settlement_manipulation    1
  [    high] layering                    1
  [    high] spoofing                    8
  [    high] wash_trade                 12
  [     low] statistical_anomaly        33
  [  medium] position_limit             1
Total alerts: 57

Detector scorecard (precision = alert quality, recall = coverage):
  detector                 alerts   TP   FP   prec  planted  caught  recall     F1
  wash_trade                   12   12    0   1.00       12      12    1.00   1.00
  spoofing                      8    8    0   1.00       16      16    1.00   1.00
  settlement_manipulation       1    1    0   1.00       10      10    1.00   1.00
  position_limit                1    1    0   1.00      120     120    1.00   1.00
  statistical_anomaly          33   30    3   0.91       12      12    1.00   0.95
  layering                      1    1    0   1.00       23      23    1.00   1.00
  insider_timing                1    1    0   1.00       14      14    1.00   1.00
```

The synthetic generator plants known abuse patterns with labels, so every
detector is scored on **precision *and* recall**, not just recall — because the
hard part of surveillance is catching abuse *without* drowning analysts in false
positives. Note the `statistical_anomaly` detector deliberately scores below 1.0:
a naive z-score over heavy-tailed trade size structurally over-flags the tail,
which is why it is low-severity and why robust calibration matters (see
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)). The near-perfect structural-detector
scores are unit-tests of the logic on clean synthetic data, **not** a claim of
live performance.

## Design notes

- **Auditable, not black-box.** Each alert carries the `evidence_ids` that
  triggered it, so a reviewer can trace any flag back to source trades/orders —
  the standard a regulated surveillance function is held to.
- **Severity-ranked blotter.** Alerts are ordered critical → low so an analyst
  triages the most material exceptions first.
- **Calibration-aware.** Every threshold lives in `surveillance/config.py` with a
  documented rationale, and detectors are scored on precision *and* recall — the
  false-positive cost is treated as first-class, because alert fatigue is the
  real failure mode of a surveillance function.
- **Tested.** `pytest` covers each detector's true-positive and clean-data
  (no false-positive) behavior, the scoring math, plus empty-input safety.
- **Extensible.** Detectors share one alert schema; adding a new pattern
  (e.g. cross-market manipulation, insider-timing around event news) is a single
  function returning the same columns.

## Repository layout

```
data/generate_synthetic_data.py   labeled synthetic trade/order generator
surveillance/detectors.py         seven market-abuse detectors
surveillance/config.py            centralized, documented detector thresholds
surveillance/runner.py            orchestration + severity-ranked blotter
surveillance/metrics.py           precision/recall/F1 scoring vs. ground truth
run_surveillance.py               CLI entry point (+ --validate scorecard)
docs/METHODOLOGY.md               typology mapping, threshold rationale, limits
tests/test_detectors.py           pytest suite
```

## Disclaimer

Built independently with synthetic data for portfolio purposes. Not affiliated
with or using any data from Kalshi or any exchange. Detector thresholds are
illustrative and would be calibrated to real venue microstructure in practice.
