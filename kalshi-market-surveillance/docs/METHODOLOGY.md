# Detection Methodology

This document is the part a surveillance reviewer actually cares about: what each
detector keys on, which regulatory typology it maps to, why its thresholds are
set where they are, what makes it fire falsely, and where the whole approach
stops. Thresholds live in [`surveillance/config.py`](../surveillance/config.py)
so calibration is one auditable place rather than scattered magic numbers.

A note on philosophy up front: catching abuse is the easy 10%. The hard 90% is
**calibration** — keeping recall high without burying analysts in false
positives, and being able to defend every threshold to an exchange or the CFTC.
That is why this project measures *precision and recall*, not just recall, and
why thresholds are explicit and documented.

---

## Detectors

### 1. Wash trading — `detect_wash_trades`
- **Typology:** Wash trading / self-matching (CEA §4c(a), CFTC; exchange
  self-trade prevention rules). A trade with no genuine transfer of beneficial
  ownership — used to paint volume or activity.
- **Logic:** Flags trades where `buyer == seller`, or where the two sides are a
  known linked pair (shared beneficial owner) supplied as exogenous intelligence.
- **Why a linked-account list:** True wash trading rarely uses one account on
  both sides; it routes through related accounts. The linked-pair input is how a
  real surveillance team injects KYC / beneficial-ownership intelligence the raw
  tape cannot reveal.
- **False-positive sources:** Legitimate give-up / allocation trades between
  accounts under one manager; an over-broad linked list. Calibration is mostly
  curating the linked-account intelligence, not a numeric threshold.

### 2. Spoofing / layering (single oversized order) — `detect_spoofing`
- **Typology:** Spoofing (Dodd-Frank §747; CEA §4c(a)(5)(C)). Entering
  non-bona-fide orders to create false depth, then canceling before execution.
- **Logic:** On each `(account, market, side)`, a `place` of top-tail size
  (≥ 95th percentile) followed by a `cancel` within the cancel window, with no
  intervening fill.
- **Threshold rationale:** The 95th-percentile size adapts to each dataset
  rather than fixing a raw quantity that drifts as the market grows. The 10s
  cancel window is deliberately tight to favour precision — genuine quoting rests
  longer than a few seconds.
- **False-positive sources:** Fast, legitimate market-making that re-prices
  quickly; widening the window or lowering the size percentile inflates FPs.

### 3. Layering / order-to-trade ratio — `detect_layering`
- **Typology:** Layering / excessive messaging (same statutory basis as
  spoofing; also exchange order-to-trade-ratio rules). Distinct from #2: the
  signal is *many* non-bona-fide orders, not one big one.
- **Logic:** For each `(account, market)` with at least `layering_min_orders`
  decided orders, flag a cancel-to-fill ratio ≥ `layering_cancel_ratio` (0.80).
- **Threshold rationale:** The minimum-order floor stops the ratio from firing on
  an account that placed one order and canceled it. 80% cancels with almost no
  fills is well outside normal two-sided behaviour.
- **False-positive sources:** Legitimate liquidity providers naturally run high
  cancel ratios; in production this is tuned per participant class, not globally.

### 4. Settlement manipulation / marking-the-close — `detect_settlement_manipulation`
- **Typology:** Marking-the-close / settlement-price manipulation (CEA §6(c),
  §9(a)(2)). Driving the print in the resolution window to influence settlement.
- **Logic:** In each market's final `settlement_close_window_s` (10 min), if the
  print moved ≥ `settlement_ramp_threshold` (15c) *and* one account drove
  ≥ `settlement_dominance_share` (50%) of aggressive buy volume, flag that
  account.
- **Threshold rationale:** Two conditions must co-occur — a material price move
  *and* concentration — because either alone is common and benign. 15c on a 1–99
  scale is a real move, not noise; 50% dominance is a defensible "one actor drove
  it" line.
- **False-positive sources:** Thin closes where a single large legitimate order
  both moves price and dominates volume; genuine end-of-event news.

### 5. Position-limit breach — `detect_position_limit_breaches`
- **Typology:** Position-limit violation (CEA §4a; exchange contract limits).
- **Logic:** Net position per `(account, market)` = longs − shorts; flag any
  magnitude over `position_limit` (25,000). Evidence is the full set of
  contributing trade IDs, so the exposure traces back to source fills.
- **Threshold rationale:** A hard regulatory/contract number, not a statistical
  one — so the only judgement is the limit itself.
- **False-positive sources:** Few, by design; mostly stale reference data on what
  the actual contract limit is, or hedged/offsetting positions not netted here.

### 6. Statistical anomaly (size outlier) — `detect_statistical_anomalies`
- **Typology:** Unsupervised outlier flow — a triage signal, not a named abuse.
- **Logic:** Per market, flag trades whose size is ≥ `anomaly_z_threshold` (4σ)
  from the market mean.
- **Threshold rationale & honest limitation:** This is the **noisiest** detector,
  which is exactly why it is `low` severity and held to a strict 4σ. On the
  synthetic data it scores ~0.91 precision — it correctly surfaces the planted
  outliers (and large abuse trades from other typologies) but also flags a few
  genuinely large *clean* trades. That is the point: **a Gaussian z-score on
  heavy-tailed trade-size data structurally over-flags the tail.** In production
  this is where robust statistics (median / MAD), per-account baselining, and
  seasonality matter, and where most alert-tuning effort goes.
- **False-positive sources:** The fat right tail of legitimate size; thin markets
  where σ is small.

### 7. Insider timing — `detect_insider_timing` *(prediction-market-specific)*
- **Typology:** Insider trading on the resolution / trading on material
  non-public information about the real-world outcome.
- **Why event contracts are different:** In equities the manipulable object is
  the *price*. In a binary event contract the manipulable object is often
  **reality itself** — the outcome the contract resolves to. An actor with
  non-public knowledge of the resolution (a poll, a ruling, a data release) can
  sit out the market and then accumulate aggressively right before settlement.
- **Logic:** Per market, take the final `insider_window_s` before the last
  print. Flag accounts that (a) traded the market at most
  `insider_dormant_max_prior` times before that window ("dormant") and (b) build a
  net aggressive position ≥ `insider_min_position` inside it.
- **Threshold rationale:** Dormancy is the discriminator — established
  participants accumulating late is ordinary; a previously-absent account
  suddenly loading up just before resolution is the signal. The drift here is
  intentionally decoupled from price size so this is distinct from
  marking-the-close.
- **False-positive sources:** New legitimate entrants; accounts whose first
  activity in a market happens to fall late by coincidence.

---

## Prediction-market manipulation: what generic surveillance misses

Detectors 1–6 are the standard equities/futures battery. They are necessary but
not sufficient for event contracts, where the novel attack surface includes:

- **Resolution manipulation.** Influencing or fabricating the real-world outcome
  or its reported source, rather than the order book. Surveillance has to reach
  *outside* the tape — to the resolution source and the actors who can move it.
- **Insider trading on the event** (detector #7). The edge is knowledge of the
  outcome, not of order flow.
- **Cross-venue games.** Coordinated positioning across Kalshi and other venues
  (e.g. Polymarket) where the same event trades; manipulating the cheaper/thinner
  venue to mark the other. Catching this needs cross-venue data the single-venue
  tape does not contain.
- **Coordinated information campaigns.** Pushing narratives to move the crowd's
  probability estimate, then trading against the move.

The honest position: this repo demonstrates the structural-abuse battery plus one
prediction-market-native typology. The cross-venue and resolution-source
typologies require data feeds beyond a single venue's trade/order tape and are
noted here as the natural next build, not claimed as implemented.

---

## Validation & limitations

- **Validation is against planted ground truth.** The generator writes every
  injected abuse to `labels.csv`; [`surveillance/metrics.py`](../surveillance/metrics.py)
  scores per-detector precision (alert quality), recall (coverage) and F1. An
  alert is a true positive if its evidence cites any labeled abuse row and a
  false positive if every cited row is clean.
- **Synthetic ≠ real.** The near-perfect scores on the structural detectors are a
  property of clean synthetic data with calibrated thresholds — they are *unit
  tests for the logic*, not a claim of live performance. On real venue
  microstructure, precision is materially lower and the thresholds here would be
  re-tuned against historical true/false-positive rates and re-validated on a
  schedule.
- **Thresholds are illustrative**, sized to this dataset. Real calibration is
  per-market and continuous.
- **Single-venue, trade/order tape only.** No KYC graph beyond the supplied
  linked pair, no cross-venue feed, no resolution-source monitoring.
