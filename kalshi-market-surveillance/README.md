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
| `spoofing` | Spoofing / layering | Large orders placed then canceled within a short window without execution — false depth. |
| `settlement_manipulation` | Marking-the-close | One account dominating aggressive flow and ramping the print into the resolution window. |
| `position_limit` | Limit breach | Net position in a market exceeding the contract position limit. |
| `statistical_anomaly` | Outlier flow | Trade size that is a per-market statistical outlier (z-score). |

## Quick start

```bash
pip install -r requirements.txt
python data/generate_synthetic_data.py     # build labeled synthetic data
python run_surveillance.py --validate       # run detectors + score recall vs ground truth
pytest -q                                   # run the test suite
```

## Example output

```
Alert summary by detector / severity:
  [critical] settlement_manipulation    1
  [    high] spoofing                    8
  [    high] wash_trade                 16
  [     low] statistical_anomaly        19
Total alerts: 44

Detection recall vs. planted abuse (ground truth):
  settlement_ramp    caught 10/10 planted ids
  spoof              caught 16/16 planted ids
  wash               caught 12/12 planted ids
```

The synthetic generator plants known abuse patterns with labels, so every
detector is measured against ground truth rather than asserted by hand.

## Design notes

- **Auditable, not black-box.** Each alert carries the `evidence_ids` that
  triggered it, so a reviewer can trace any flag back to source trades/orders —
  the standard a regulated surveillance function is held to.
- **Severity-ranked blotter.** Alerts are ordered critical → low so an analyst
  triages the most material exceptions first.
- **Tested.** `pytest` covers each detector's true-positive and clean-data
  (no false-positive) behavior, plus empty-input safety.
- **Extensible.** Detectors share one alert schema; adding a new pattern
  (e.g. cross-market manipulation, insider-timing around event news) is a single
  function returning the same columns.

## Repository layout

```
data/generate_synthetic_data.py   labeled synthetic trade/order generator
surveillance/detectors.py         five market-abuse detectors
surveillance/runner.py            orchestration + severity-ranked blotter
run_surveillance.py               CLI entry point (+ --validate recall scoring)
tests/test_detectors.py           pytest suite
```

## Disclaimer

Built independently with synthetic data for portfolio purposes. Not affiliated
with or using any data from Kalshi or any exchange. Detector thresholds are
illustrative and would be calibrated to real venue microstructure in practice.
