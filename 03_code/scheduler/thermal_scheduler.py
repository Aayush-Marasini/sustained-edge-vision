"""
thermal_scheduler.py
====================
Task 12 (WorkPlan §6.4): Proactive state-aware DVFS scheduler decision policy.

Replaces _decide_config_placeholder() in scheduler_runtime.py.

Design
------
The scheduler observes the state vector s(t) = {T, T_dot, U, U_dot, f, f_dot}
produced by derivatives.py and decides which DVFS state {S0, S1, S2} to apply
via dvfs_control.py. Decisions are written to scheduler_decisions.csv.

The policy is proactive: it reacts to T_dot (thermal derivative) before T
crosses a hard threshold, giving the heatsink time to respond within the
thermal time constant τ ≈ 10s.

Safety invariants (never violated regardless of signal values):
  1. Hysteresis: ΔT_hyst = 5.0°C >> 3·σ_T = 1.75°C. Prevents noise oscillation.
  2. Dwell time: t_dwell = 20s ≥ 2·τ_thermal. Prevents thrashing.
  3. Confirmation: N_confirm = 3 consecutive samples before any escalation.
     Prevents single-spike false positives.
  4. Recovery is always conservative: only one step at a time (S2→S1, S1→S0).

Thresholds (grounded in Task 20 empirical data + calibration):
  T_escalate_S0_to_S1 = 75.0°C  (proactive: 9.9°C before S0 plateau of 84.9°C)
  T_escalate_S1_to_S2 = 79.0°C  (proactive: 2.3°C before S1 plateau of 81.3°C)
  T_recover_S2_to_S1  = 71.0°C  (8°C gap from escalate threshold = 4.6× hysteresis)
  T_recover_S1_to_S0  = 68.0°C  (7°C gap from escalate threshold = 4.0× hysteresis)
  T_dot_proactive     = 0.5°C/s (6.6× σ_{T_dot}=0.0759: strong rising signal)

All gaps satisfy ΔT_hyst > 3·σ_T = 1.75°C by a large margin.

WorkPlan grounding
------------------
- Task 12 (§6.4): implement decision policy with hysteresis and dwell-time.
- Task 13 (§6.5): HCC mechanism — stub included, implement in next task.
- Task 21 (§8.2): this policy runs the 5-15 min pilot tests.
- Task 28 (§9.4): policy stability ablation (remove hysteresis/dwell, compare).

Paper contribution
------------------
§III.D System Design: scheduler decision policy description.
§V.C Main results: throttle events, FPS stability under proposed scheduler.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State definitions (mirrors dvfs_control.STATES — import avoided to keep
# this module testable without Pi hardware)
# ---------------------------------------------------------------------------

class DvfsState(str, Enum):
    S0 = "S0"   # 2400 MHz — max performance
    S1 = "S1"   # 1800 MHz — moderate cooling
    S2 = "S2"   # 1500 MHz — aggressive cooling

    def cap_khz(self) -> int:
        return {"S0": 2_400_000, "S1": 1_800_000, "S2": 1_500_000}[self.value]

    def is_more_aggressive_than(self, other: "DvfsState") -> bool:
        """S2 > S1 > S0 in cooling aggressiveness."""
        order = {DvfsState.S0: 0, DvfsState.S1: 1, DvfsState.S2: 2}
        return order[self] > order[other]


# ---------------------------------------------------------------------------
# Policy parameters — all grounded in empirical measurements
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SchedulerConfig:
    """
    All thresholds in one place. Frozen so accidental mutation is caught
    at import time. Change here → CHANGELOG entry required.

    Threshold derivation:
      T_escalate_S0_to_S1: S0 T_plateau = 84.9°C. Proactive trigger at 75°C
        gives 9.9°C of headroom — enough for τ_thermal = 10s response.
      T_escalate_S1_to_S2: S1 T_plateau = 81.3°C. Trigger at 79°C gives 2.3°C
        headroom. Tight but necessary: S1 itself is in the thermal danger zone.
      T_recover_S2_to_S1: 71°C. Gap from T_escalate_S1_to_S2 = 8°C = 4.6×σ_T_hyst.
      T_recover_S1_to_S0: 68°C. Gap from T_escalate_S0_to_S1 = 7°C = 4.0×σ_T_hyst.
      T_dot_proactive: 0.5°C/s = 6.6×σ_{T_dot}. Only fires on strong heating.
      dwell_time_s: 20s = 2×τ_thermal. Prevents switching before heatsink responds.
      n_confirm: 3 samples at 2Hz = 1.5s. Rejects single-spike transients.
    """
    # Escalation thresholds (°C) — go to more aggressive cooling
    T_escalate_S0_to_S1: float = 75.0
    T_escalate_S1_to_S2: float = 79.0

    # Recovery thresholds (°C) — return to less aggressive cooling
    T_recover_S2_to_S1: float = 71.0
    T_recover_S1_to_S0: float = 68.0

    # Proactive trigger: escalate early if T_dot exceeds this (°C/s)
    # regardless of absolute T, if T is above a minimum concern level
    T_dot_proactive: float = 0.5       # °C/s — 6.6× σ_{T_dot}
    T_dot_concern_floor: float = 65.0  # °C — only use T_dot trigger above this

    # Anti-oscillation safeguards
    dwell_time_s: float = 20.0   # minimum seconds between ANY state change
    n_confirm: int = 3            # consecutive samples required before escalation

    # Derived floor (informational — not used in logic, documents calibration)
    sigma_T: float = 0.5835      # °C — from Phase B idle calibration
    sigma_T_dot: float = 0.0759  # °C/s — from DEFAULT_CONFIG_2HZ EMA


# Default config used by all paper-quality runs
DEFAULT_SCHEDULER_CONFIG = SchedulerConfig()


# ---------------------------------------------------------------------------
# Decision reasons — logged to scheduler_decisions.csv for ablation analysis
# ---------------------------------------------------------------------------

class DecisionReason(str, Enum):
    BOOT_DEFAULT        = "boot_default"
    ESCALATE_REACTIVE   = "escalate_reactive_T"      # T crossed threshold
    ESCALATE_PROACTIVE  = "escalate_proactive_T_dot" # T_dot triggered early
    RECOVER             = "recover_T_below_floor"
    DWELL_HOLD          = "dwell_hold"               # no-op: in dwell window
    CONFIRM_HOLD        = "confirm_hold"             # no-op: awaiting N_confirm
    NO_CHANGE           = "no_change"
    MISSING_SIGNAL      = "missing_signal"           # T or T_dot unavailable


# ---------------------------------------------------------------------------
# Scheduler state (mutable, one instance per run)
# ---------------------------------------------------------------------------

@dataclass
class SchedulerState:
    """Runtime state of the scheduler. Serializable for logging."""
    current_state: DvfsState = DvfsState.S0
    last_switch_monotonic: float = field(default_factory=time.monotonic)
    escalate_confirm_count: int = 0   # consecutive samples requesting escalation
    recover_confirm_count: int = 0    # consecutive samples requesting recovery
    total_decisions: int = 0
    total_state_changes: int = 0
    throttle_events_observed: int = 0


# ---------------------------------------------------------------------------
# Core decision function
# ---------------------------------------------------------------------------

def decide(
    T: Optional[float],
    T_dot: Optional[float],
    throttled_now: Optional[int],
    sched_state: SchedulerState,
    config: SchedulerConfig = DEFAULT_SCHEDULER_CONFIG,
    now_monotonic: Optional[float] = None,
) -> tuple[DvfsState, DecisionReason]:
    """
    Pure decision function: given current telemetry, return (new_state, reason).

    Parameters
    ----------
    T : float | None
        Current EMA-smoothed SoC temperature (°C). None if sensor failed.
    T_dot : float | None
        Current EMA temperature derivative (°C/s). None if insufficient history.
    throttled_now : int | None
        Bit 0 of vcgencmd get_throttled bitmask (0 or 1). None if unavailable.
    sched_state : SchedulerState
        Mutable scheduler runtime state (modified in-place on state change).
    config : SchedulerConfig
        Policy parameters. Use DEFAULT_SCHEDULER_CONFIG for paper runs.
    now_monotonic : float | None
        Current monotonic time. If None, uses time.monotonic().

    Returns
    -------
    (DvfsState, DecisionReason) — the chosen state and why.

    Side effects
    ------------
    Updates sched_state.current_state, .last_switch_monotonic,
    .escalate_confirm_count, .recover_confirm_count, .total_decisions,
    .total_state_changes, .throttled_events_observed.
    """
    now = now_monotonic if now_monotonic is not None else time.monotonic()
    sched_state.total_decisions += 1

    # Track throttle events for paper metric
    if throttled_now == 1:
        sched_state.throttle_events_observed += 1

    # Missing signal guard — hold current state, do not guess
    if T is None:
        sched_state.escalate_confirm_count = 0
        sched_state.recover_confirm_count = 0
        return sched_state.current_state, DecisionReason.MISSING_SIGNAL

    current = sched_state.current_state
    time_since_switch = now - sched_state.last_switch_monotonic

    # ------------------------------------------------------------------
    # Dwell-time guard: no switching within dwell window
    # (applied to BOTH escalation and recovery — prevents thrashing)
    # ------------------------------------------------------------------
    in_dwell = time_since_switch < config.dwell_time_s
    if in_dwell:
        sched_state.escalate_confirm_count = 0
        sched_state.recover_confirm_count = 0
        return current, DecisionReason.DWELL_HOLD

    # ------------------------------------------------------------------
    # Determine desired direction based on T and T_dot
    # ------------------------------------------------------------------
    want_escalate = _should_escalate(T, T_dot, current, config)
    want_recover  = _should_recover(T, current, config)

    # ------------------------------------------------------------------
    # Confirmation counter logic
    # Escalation requires N_confirm consecutive samples.
    # Recovery is immediate (one sample sufficient — conservative direction).
    # ------------------------------------------------------------------
    if want_escalate:
        sched_state.recover_confirm_count = 0
        sched_state.escalate_confirm_count += 1
        if sched_state.escalate_confirm_count < config.n_confirm:
            return current, DecisionReason.CONFIRM_HOLD
        # Confirmed — escalate one step
        sched_state.escalate_confirm_count = 0
        new_state, reason = _escalate_one_step(current, T, T_dot, config)

    elif want_recover:
        sched_state.escalate_confirm_count = 0
        sched_state.recover_confirm_count += 1
        # Recovery: also require N_confirm to avoid premature recovery
        if sched_state.recover_confirm_count < config.n_confirm:
            return current, DecisionReason.CONFIRM_HOLD
        sched_state.recover_confirm_count = 0
        new_state, reason = _recover_one_step(current)

    else:
        sched_state.escalate_confirm_count = 0
        sched_state.recover_confirm_count = 0
        return current, DecisionReason.NO_CHANGE

    # ------------------------------------------------------------------
    # Apply state change
    # ------------------------------------------------------------------
    if new_state != current:
        log.info(
            "Scheduler: %s → %s  reason=%s  T=%.1f°C  T_dot=%s°C/s  "
            "dwell=%.1fs",
            current.value, new_state.value, reason.value,
            T,
            f"{T_dot:.3f}" if T_dot is not None else "None",
            time_since_switch,
        )
        sched_state.current_state = new_state
        sched_state.last_switch_monotonic = now
        sched_state.total_state_changes += 1

    return new_state, reason


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _should_escalate(
    T: float,
    T_dot: Optional[float],
    current: DvfsState,
    config: SchedulerConfig,
) -> bool:
    """Return True if we should move to a more aggressive cooling state."""
    if current == DvfsState.S2:
        return False  # already at maximum cooling

    if current == DvfsState.S0:
        # Reactive threshold
        if T >= config.T_escalate_S0_to_S1:
            return True
        # Proactive trigger: rising fast AND in concern zone
        if (T_dot is not None
                and T >= config.T_dot_concern_floor
                and T_dot >= config.T_dot_proactive):
            return True

    if current == DvfsState.S1:
        if T >= config.T_escalate_S1_to_S2:
            return True
        # Proactive: S1 plateau is already 81.3°C — any strong rise is dangerous
        if (T_dot is not None
                and T >= config.T_dot_concern_floor
                and T_dot >= config.T_dot_proactive):
            return True

    return False


def _should_recover(
    T: float,
    current: DvfsState,
    config: SchedulerConfig,
) -> bool:
    """Return True if we should move to a less aggressive cooling state."""
    if current == DvfsState.S0:
        return False  # already at minimum cooling (maximum performance)

    if current == DvfsState.S2:
        return T <= config.T_recover_S2_to_S1

    if current == DvfsState.S1:
        return T <= config.T_recover_S1_to_S0

    return False


def _escalate_one_step(
    current: DvfsState,
    T: float,
    T_dot: Optional[float],
    config: SchedulerConfig,
) -> tuple[DvfsState, DecisionReason]:
    """Move one step toward more aggressive cooling."""
    if current == DvfsState.S0:
        new = DvfsState.S1
    elif current == DvfsState.S1:
        new = DvfsState.S2
    else:
        return current, DecisionReason.NO_CHANGE

    # Determine whether this was reactive or proactive
    thresholds = {
        DvfsState.S0: config.T_escalate_S0_to_S1,
        DvfsState.S1: config.T_escalate_S1_to_S2,
    }
    if T >= thresholds.get(current, float("inf")):
        reason = DecisionReason.ESCALATE_REACTIVE
    else:
        reason = DecisionReason.ESCALATE_PROACTIVE

    return new, reason


def _recover_one_step(
    current: DvfsState,
) -> tuple[DvfsState, DecisionReason]:
    """Move one step toward less aggressive cooling (more performance)."""
    if current == DvfsState.S2:
        return DvfsState.S1, DecisionReason.RECOVER
    if current == DvfsState.S1:
        return DvfsState.S0, DecisionReason.RECOVER
    return current, DecisionReason.NO_CHANGE