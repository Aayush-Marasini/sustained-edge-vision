"""
reactive_threshold_scheduler.py
================================
Task 18 (WorkPlan §7.2): Reactive-Threshold baseline scheduler.

This is the STRAWMAN baseline. It represents the simplest possible
software thermal controller: a two-threshold hysteresis switch with
no derivative signal, no confirmation window, and no dwell time.

Design
------
- If T >= T_high AND current != S2: switch immediately to S2
- If T <= T_low  AND current == S2: switch immediately to S0
- No T_dot signal used
- No N_confirm: acts on single sample
- No dwell time: can switch on every sample

Why S2 (not S1) as the cooling state
-------------------------------------
S1's thermal plateau is 81.3°C — above the ~80°C hardware throttle
onset. A reactive controller switching to S1 at T_high=78°C cannot
prevent throttling because thermal momentum carries the system through
80°C before S1's lower power dissipation takes effect.
S2's plateau is 73.1°C — safely below throttle. This is the only
state a reactive controller can use to guarantee throttle prevention.

This limitation is the core motivation for the proactive scheduler
(thermal_scheduler.py): by acting earlier via T_dot, it can use S1
(higher FPS) and still prevent throttle.

Paper grounding
---------------
§V.C: Reactive-Threshold is the primary strawman comparison.
      The gap in FPS between Reactive-Threshold and the proactive
      scheduler quantifies the value of the derivative signal.

WorkPlan grounding
------------------
Task 18 (§7.2): implement and run baseline controllers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DvfsState(str, Enum):
    S0 = "S0"   # 2400 MHz
    S1 = "S1"   # 1800 MHz (not used by this controller)
    S2 = "S2"   # 1500 MHz


class DecisionReason(str, Enum):
    BOOT_DEFAULT     = "boot_default"
    ESCALATE_TO_S2   = "reactive_escalate_to_S2"
    RECOVER_TO_S0    = "reactive_recover_to_S0"
    NO_CHANGE        = "no_change"
    MISSING_SIGNAL   = "missing_signal"


@dataclass
class ReactiveThresholdConfig:
    """
    Two thresholds only. No derivative, no dwell, no confirmation.

    T_high: switch to S2 when T exceeds this
    T_low:  switch back to S0 when T drops below this
    Gap = T_high - T_low = 8°C = 13.7×σ_T — same hysteresis width
    as the proactive scheduler's S1/S2 band, for fair comparison.
    """
    T_high: float = 78.0   # °C — escalate to S2
    T_low:  float = 70.0   # °C — recover to S0


DEFAULT_REACTIVE_CONFIG = ReactiveThresholdConfig()


@dataclass
class ReactiveThresholdState:
    current_state: DvfsState = DvfsState.S0
    total_decisions: int = 0
    total_state_changes: int = 0
    throttle_events_observed: int = 0


def decide_reactive(
    T: Optional[float],
    throttled_now: Optional[int],
    sched_state: ReactiveThresholdState,
    config: ReactiveThresholdConfig = DEFAULT_REACTIVE_CONFIG,
) -> tuple[DvfsState, DecisionReason]:
    """
    Reactive threshold decision. No time argument needed — no dwell.

    Parameters
    ----------
    T             : smoothed temperature (°C), or None if sensor failed
    throttled_now : bit 0 of throttle bitmask (0 or 1), or None
    sched_state   : mutable runtime state (modified in place)
    config        : threshold parameters

    Returns
    -------
    (DvfsState, DecisionReason)
    """
    sched_state.total_decisions += 1

    if throttled_now == 1:
        sched_state.throttle_events_observed += 1

    if T is None:
        return sched_state.current_state, DecisionReason.MISSING_SIGNAL

    current = sched_state.current_state

    # Escalate: any non-S2 state → S2 immediately
    if T >= config.T_high and current != DvfsState.S2:
        new_state = DvfsState.S2
        reason    = DecisionReason.ESCALATE_TO_S2

    # Recover: S2 → S0 immediately
    elif T <= config.T_low and current == DvfsState.S2:
        new_state = DvfsState.S0
        reason    = DecisionReason.RECOVER_TO_S0

    else:
        return current, DecisionReason.NO_CHANGE

    sched_state.current_state = new_state
    sched_state.total_state_changes += 1
    return new_state, reason