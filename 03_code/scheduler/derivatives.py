"""
derivatives.py
==============
Online smoothing and derivative estimation for the system state vector.

Grounding
---------
- proposal_v2.pdf §4 defines the state vector:
      s(t) = [T(t), T_dot(t), U(t), U_dot(t), V(t), V_dot(t)]
  Temporal derivatives serve as lead indicators for impending stress.
  §8 commits to heuristic (not learned) policies, which anchors the
  design choice below at the simplest defensible complexity tier.
- WorkPlan_marked.pdf Task 11 (§6.3) requires: exact units, chosen
  smoothing windows, chosen derivative calculation method, and signal
  stability tests under idle and stress conditions.

Design decisions (justification for paper §III.B)
-------------------------------------------------
1. Smoothing: causal exponential moving average (EMA) with signal-
   specific alpha. Rationale: O(1) per update, one parameter, maps
   cleanly to a time constant tau_smooth ~= dt * (1 - alpha) / alpha.
   Rejected alternatives: median filter introduces non-linear lag that
   complicates derivative interpretation; Savitzky-Golay is more
   accurate but adds sample buffering; Kalman is overkill for the
   heuristic tier committed to in the proposal.

2. Derivative: stride-k backward finite difference on the *smoothed*
   signal. Rationale: strictly causal (no future samples), required
   for real-time proactive scheduling where lead time is the whole
   point. Stride k > 1 trades a small amount of responsiveness for
   substantial noise attenuation.

3. Signal-specific parameters: temperature has a thermal time constant
   of seconds; CPU utilization is bursty at the frame level; voltage
   responds near-instantly but steps discretely under DVFS. One global
   smoothing setting is wrong for all three.

Per-signal defaults at 5 Hz (dt = 0.2 s)
----------------------------------------
Temperature (temp_soc) parameters empirically tuned via Phase B.5
calibration sweep (2026-04-26). Selected Pareto-optimal configuration
with lowest noise (0.0759 C/s std dev) subject to 10-second 90% rise
time budget (matching Pi 5 passive cooling thermal RC time constant):

  temp_soc   alpha=0.10  stride=10    tau_smooth ~= 1.898 s, rate window 2.0 s

CPU utilization and voltage retain initial heuristic values pending
Phase D baseline profiling:

  cpu_util   alpha=0.10  stride=15    tau_smooth ~= 1.898 s, rate window 3.0 s
  volt_core  alpha=0.30  stride=5     tau_smooth ~= 0.561 s, rate window 1.0 s

Per-signal defaults at 2 Hz (dt = 0.5 s) — S1.5 recalibration
----------------------------------------------------------------
Alpha values recalculated to PRESERVE tau_smooth from 5 Hz config.
Formula: alpha_new = 1 - exp(-dt_new / tau_smooth)

Derivation:
  temp_soc:  tau=1.898s -> alpha = 1 - exp(-0.5/1.898) = 0.2314
  cpu_util:  tau=1.898s -> alpha = 1 - exp(-0.5/1.898) = 0.2314
  volt_core: tau=0.561s -> alpha = 1 - exp(-0.5/0.561) = 0.5901
  cpu_freq:  tau=0.561s -> alpha = 1 - exp(-0.5/0.561) = 0.5901
  mem_util:  tau=0.694s -> alpha = 1 - exp(-0.5/0.694) = 0.5120

Stride values recalculated to PRESERVE rate window duration:
  rate_window = stride * dt -> stride_new = rate_window / dt_new

  temp_soc:  window=2.0s  -> stride = 2.0/0.5 = 4
  cpu_util:  window=3.0s  -> stride = 3.0/0.5 = 6
  volt_core: window=1.0s  -> stride = 1.0/0.5 = 2
  cpu_freq:  window=1.0s  -> stride = 1.0/0.5 = 2
  mem_util:  window=2.0s  -> stride = 2.0/0.5 = 4

Change log
----------
v0.1 (2026-04-19): initial implementation.
v0.5 (2026-04-26): Phase B.5 EMA tuning. alpha=0.10, stride=10 for temp_soc.
v0.7.3 (2026-04-29): S1.5 — added DEFAULT_CONFIG_2HZ. Alpha/stride recalculated
  to preserve tau_smooth and rate_window at new 2 Hz default sampling rate.
  DEFAULT_CONFIG_5HZ retained for backward compatibility and unit tests.

Change log
----------
v0.1 (2026-04-19): initial implementation following the design agreed
  in the Task 10/11 planning discussion.
v0.5 (2026-04-26): Phase B.5 EMA parameter tuning complete. Updated
  temp_soc alpha from 0.20 to 0.10 and derivative_stride from 10 to 10
  (stride unchanged, alpha tuned down for 2.1x lower noise variance).
  Selection based on Pareto sweep over 20 (alpha, stride) pairs on 4
  calibration traces (2x idle, 2x stress-ng matrixprod). Noise metric:
  std dev of T_dot during steady states. Lag metric: 90% rise time
  during heating ramp when stress-ng starts. See tuning_report.md.
"""

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple


# -- Single-signal estimator --------------------------------------------------


@dataclass
class SignalEstimator:
    """
    Maintains EMA-smoothed value and stride-k backward finite difference
    for a single scalar telemetry signal.

    Parameters
    ----------
    alpha : float
        EMA factor in (0, 1]. Larger = less smoothing, more responsive.
        Approximate first-order time constant tau = dt * (1 - alpha) / alpha.
    derivative_stride : int
        Sample lag between the two endpoints of the finite difference.
        Effective rate window = derivative_stride * dt seconds.
    dt : float
        Sampling interval in seconds.
    """

    alpha: float
    derivative_stride: int
    dt: float

    _smoothed: Optional[float] = field(default=None, init=False)
    _history: Deque[float] = field(default_factory=deque, init=False)

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha <= 1.0):
            raise ValueError(f"alpha must be in (0, 1], got {self.alpha}")
        if self.derivative_stride < 1:
            raise ValueError(f"derivative_stride must be >= 1, got {self.derivative_stride}")
        if self.dt <= 0:
            raise ValueError(f"dt must be positive, got {self.dt}")
        self._history = deque(maxlen=self.derivative_stride + 1)

    def update(self, raw: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        """
        Ingest one raw sample.

        Returns
        -------
        (smoothed, rate_per_second)
            smoothed : the EMA-smoothed signal value, or None if no valid
                       sample has yet been observed.
            rate_per_second : the stride-k finite difference in units-per-
                              second, or None until the history buffer is
                              full.

        Bad samples (None / NaN / inf) carry forward the last smoothed
        value rather than poisoning the EMA. This matches the None output
        of telemetry_pipeline.py on sensor failure.
        """
        if raw is None or not _is_finite(raw):
            if self._smoothed is None:
                return (None, None)
            # propagate last smoothed value so derivative window stays aligned
            self._history.append(self._smoothed)
            return (self._smoothed, self._current_rate())

        if self._smoothed is None:
            self._smoothed = float(raw)
        else:
            self._smoothed = self.alpha * float(raw) + (1.0 - self.alpha) * self._smoothed

        self._history.append(self._smoothed)
        return (self._smoothed, self._current_rate())

    def _current_rate(self) -> Optional[float]:
        if len(self._history) < self.derivative_stride + 1:
            return None
        return (self._history[-1] - self._history[0]) / (self.derivative_stride * self.dt)

    def reset(self) -> None:
        self._smoothed = None
        self._history.clear()


def _is_finite(x: float) -> bool:
    return math.isfinite(x)


# -- State vector builder -----------------------------------------------------


# ---------------------------------------------------------------------------
# 5 Hz config (dt = 0.2 s) — Phase B.5 empirically tuned (2026-04-26)
# Retained for backward compatibility and unit tests.
# ---------------------------------------------------------------------------
DEFAULT_CONFIG_5HZ: Dict[str, Dict[str, float]] = {
    "temp_soc":  {"alpha": 0.10, "derivative_stride": 10, "dt": 0.2},
    "cpu_util":  {"alpha": 0.10, "derivative_stride": 15, "dt": 0.2},
    "volt_core": {"alpha": 0.30, "derivative_stride": 5,  "dt": 0.2},
    # Auxiliary signals: tracked, derivatives informational only.
    "cpu_freq":  {"alpha": 0.30, "derivative_stride": 5,  "dt": 0.2},
    "mem_util":  {"alpha": 0.20, "derivative_stride": 10, "dt": 0.2},
}

# ---------------------------------------------------------------------------
# 2 Hz config (dt = 0.5 s) — S1.5 recalibration (2026-04-29)
# Alpha and stride recalculated to preserve tau_smooth and rate_window.
# Formula: alpha_new = 1 - exp(-dt_new / tau_smooth)
#          stride_new = round(rate_window / dt_new)
# This is the PRODUCTION default since v0.7.2 set sampling_rate_hz=2.0.
# ---------------------------------------------------------------------------
DEFAULT_CONFIG_2HZ: Dict[str, Dict[str, float]] = {
    "temp_soc":  {"alpha": 0.2314, "derivative_stride": 4,  "dt": 0.5},
    "cpu_util":  {"alpha": 0.2314, "derivative_stride": 6,  "dt": 0.5},
    "volt_core": {"alpha": 0.5901, "derivative_stride": 2,  "dt": 0.5},
    # Auxiliary signals.
    "cpu_freq":  {"alpha": 0.5901, "derivative_stride": 2,  "dt": 0.5},
    "mem_util":  {"alpha": 0.5120, "derivative_stride": 4,  "dt": 0.5},
}

# Production default — matches telemetry_pipeline.py default sampling rate.
# Update this alias when sampling rate changes; do NOT silently change
# DEFAULT_CONFIG_5HZ or DEFAULT_CONFIG_2HZ values without a CHANGELOG entry.
DEFAULT_CONFIG = DEFAULT_CONFIG_2HZ


# Map from telemetry_raw.csv column names to estimator keys.
_COLUMN_TO_SIGNAL = {
    "temp_soc_c":       "temp_soc",
    "cpu_util_percent": "cpu_util",
    "volt_core_v":      "volt_core",
    "cpu_freq_mhz":     "cpu_freq",
    "mem_util_percent": "mem_util",
}


class StateVectorBuilder:
    """
    Converts a stream of raw telemetry samples into the state vector
    defined in proposal_v2.pdf §4.

    The return value of update() is a dict with the formal state vector
    keys T, T_dot, U, U_dot, V, V_dot plus auxiliary signals f, f_dot,
    mem. Rate fields are None until the corresponding estimator has
    enough history to produce a finite difference.

    Auxiliary signals are included so the downstream scheduler can
    disambiguate DVFS-step voltage changes (correlated with f_dot) from
    genuine voltage sag (V drops while f is steady).
    """

    def __init__(self, config: Optional[Dict[str, Dict[str, float]]] = None):
        cfg = config or DEFAULT_CONFIG
        self._estimators: Dict[str, SignalEstimator] = {
            name: SignalEstimator(**params) for name, params in cfg.items()
        }

    def update(self, raw_sample: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
        """
        raw_sample can be either a dict using internal signal names (e.g.
        'temp_soc') or a row dict from telemetry_raw.csv (e.g.
        'temp_soc_c'). Either works; column names are translated.
        """
        smoothed: Dict[str, Optional[float]] = {}
        rates: Dict[str, Optional[float]] = {}

        for signal_name, estimator in self._estimators.items():
            raw_value = raw_sample.get(signal_name)
            if raw_value is None:
                # fall back to CSV column name
                for col, sig in _COLUMN_TO_SIGNAL.items():
                    if sig == signal_name:
                        raw_value = raw_sample.get(col)
                        break
            s, r = estimator.update(_to_float(raw_value))
            smoothed[signal_name] = s
            rates[signal_name] = r

        return {
            # proposal_v2.pdf §4 formal state vector
            "T":     smoothed["temp_soc"],
            "T_dot": rates["temp_soc"],
            "U":     smoothed["cpu_util"],
            "U_dot": rates["cpu_util"],
            "V":     smoothed["volt_core"],
            "V_dot": rates["volt_core"],
            # Auxiliary (useful for DVFS-step disambiguation)
            "f":     smoothed["cpu_freq"],
            "f_dot": rates["cpu_freq"],
            "mem":   smoothed["mem_util"],
        }


def _to_float(x) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None