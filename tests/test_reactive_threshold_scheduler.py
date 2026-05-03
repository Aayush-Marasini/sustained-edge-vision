"""
Unit tests for reactive_threshold_scheduler.py (Task 18 baseline).

Tests verify:
1. Cold start defaults to S0.
2. Escalates to S2 (not S1) at T_high.
3. Recovers to S0 at T_low.
4. No dwell: switches on consecutive samples without waiting.
5. Missing signal holds current state.
6. Throttle events are counted.
7. Does NOT use S1 as an intermediate state.

Run: pytest tests/test_reactive_threshold_scheduler.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "03_code"))

from scheduler.reactive_threshold_scheduler import (
    DEFAULT_REACTIVE_CONFIG as CFG,
    DecisionReason,
    DvfsState,
    ReactiveThresholdState,
    decide_reactive,
)


def fresh() -> ReactiveThresholdState:
    return ReactiveThresholdState()


def test_cold_start_is_S0():
    s = fresh()
    state, reason = decide_reactive(T=50.0, throttled_now=0, sched_state=s)
    assert state == DvfsState.S0
    assert reason == DecisionReason.NO_CHANGE


def test_escalates_to_S2_not_S1():
    s = fresh()
    state, reason = decide_reactive(T=CFG.T_high + 1.0, throttled_now=0, sched_state=s)
    assert state == DvfsState.S2, "reactive controller must jump to S2, never S1"
    assert reason == DecisionReason.ESCALATE_TO_S2


def test_no_dwell_switches_every_sample():
    """Without dwell, two consecutive above-threshold samples both trigger."""
    s = fresh()
    # First sample: escalate to S2
    state1, _ = decide_reactive(T=CFG.T_high + 1.0, throttled_now=0, sched_state=s)
    assert state1 == DvfsState.S2
    # Second sample: already at S2, no change
    state2, reason2 = decide_reactive(T=CFG.T_high + 1.0, throttled_now=0, sched_state=s)
    assert state2 == DvfsState.S2
    assert reason2 == DecisionReason.NO_CHANGE
    # Drop below T_low: immediate recovery, no dwell wait
    state3, reason3 = decide_reactive(T=CFG.T_low - 1.0, throttled_now=0, sched_state=s)
    assert state3 == DvfsState.S0
    assert reason3 == DecisionReason.RECOVER_TO_S0


def test_recovery_to_S0_not_S1():
    """Reactive controller recovers directly S2→S0, never pauses at S1."""
    s = fresh()
    s.current_state = DvfsState.S2
    state, reason = decide_reactive(T=CFG.T_low - 1.0, throttled_now=0, sched_state=s)
    assert state == DvfsState.S0, "must recover to S0, not S1"
    assert reason == DecisionReason.RECOVER_TO_S0


def test_missing_signal_holds_state():
    s = fresh()
    s.current_state = DvfsState.S2
    state, reason = decide_reactive(T=None, throttled_now=None, sched_state=s)
    assert state == DvfsState.S2
    assert reason == DecisionReason.MISSING_SIGNAL


def test_throttle_events_counted():
    s = fresh()
    decide_reactive(T=50.0, throttled_now=1, sched_state=s)
    decide_reactive(T=50.0, throttled_now=1, sched_state=s)
    decide_reactive(T=50.0, throttled_now=0, sched_state=s)
    assert s.throttle_events_observed == 2


def test_no_action_between_thresholds():
    """T between T_low and T_high: no change."""
    s = fresh()
    s.current_state = DvfsState.S2
    mid_T = (CFG.T_low + CFG.T_high) / 2
    state, reason = decide_reactive(T=mid_T, throttled_now=0, sched_state=s)
    assert state == DvfsState.S2
    assert reason == DecisionReason.NO_CHANGE