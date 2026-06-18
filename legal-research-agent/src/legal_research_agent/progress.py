"""Non-deterministic progress model.

The mock — like the real system — does NOT know its own completion time
reliably and does NOT report a trustworthy ETA. What it exposes:

* a sampled total duration (clamped normal) used only internally to decide
  when to finish;
* a noisy progress percentage that trends toward 100 by completion but with
  stalls, rare small regressions, and jittery phase boundaries — so a client
  cannot derive a reliable ETA from the stream;
* occasional "complication" messages that model real-system messiness without
  changing the percentage much.

Nothing here is exposed as an ETA to clients.
"""

from __future__ import annotations

import random
from typing import Optional

from .config import settings
from .schemas import Effort

PHASES = [
    "researching",
    "retrieving statutes",
    "analyzing jurisdictions",
    "evaluating case law",
    "cross-checking citations",
    "drafting summary",
    "finalizing report",
]

COMPLICATIONS = [
    "encountered conflicting case law — expanding research scope",
    "jurisdiction boundary ambiguous — pulling additional sources",
    "statute recently amended — re-checking effective dates",
    "citation chain incomplete — retrying retrieval",
    None,
    None,
    None,
]


def sample_duration(effort: Effort) -> float:
    """Sample a real (unscaled) duration in seconds for the given effort tier."""
    if effort == Effort.quick:
        mean, sd, lo, hi = settings.quick_mean_s, settings.quick_sd_s, settings.quick_min_s, settings.quick_max_s
    elif effort == Effort.standard:
        mean, sd, lo, hi = settings.standard_mean_s, settings.standard_sd_s, settings.standard_min_s, settings.standard_max_s
    else:
        mean, sd, lo, hi = settings.deep_mean_s, settings.deep_sd_s, settings.deep_min_s, settings.deep_max_s
    value = random.gauss(mean, sd)
    return max(lo, min(hi, value))


def next_interval_s() -> float:
    """Random wall-clock interval until the next progress event (already scaled)."""
    interval = max(settings.progress_interval_min_s, random.expovariate(1.0 / settings.progress_interval_mean_s))
    return interval * settings.time_scale


def noisy_progress(elapsed_s: float, total_s: float, last_pct: float) -> tuple[float, str, Optional[str]]:
    """Return (progress_pct, phase, complication_message) for this tick.

    The percentage is a noisy function of elapsed/total with stalls and rare
    small regressions, clamped to [0, 99] until the terminal 100 at completion.
    """
    raw = 100.0 * (elapsed_s / total_s) + random.gauss(0.0, 8.0)
    raw = max(0.0, min(99.0, raw))

    r = random.random()
    if r < 0.30:
        pct = last_pct  # stall: emit the same percentage again
    elif r < 0.40:
        pct = max(0.0, last_pct - random.uniform(1.0, 4.0))  # small, brief regression
    else:
        pct = max(last_pct, raw)

    pct = max(0.0, min(99.0, pct))

    # Jittery phase boundaries: pick a phase index based on noisy pct.
    noisy = pct + random.gauss(0.0, 6.0)
    idx = min(len(PHASES) - 1, int(noisy / (100.0 / len(PHASES))))
    phase = PHASES[idx]

    complication = random.choice(COMPLICATIONS)

    return pct, phase, complication
