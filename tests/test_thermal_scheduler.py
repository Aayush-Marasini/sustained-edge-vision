"""
Unit tests for thermal_scheduler.py (Task 12).

Tests verify:
 1. Cold start defaults to S0.
 2. Reactive escalation S0→S1 requires N_confirm consecutive samples.
 3. Proactive escalation via T_dot in concern zone.
 4. Dwell-time guard blocks switching within dwell window.
 5. No double-escalation: S0→S1 only, not S0→S2 in one step.
 6. Recovery S2→S1 requires N_confirm consecutive samples.
 7. Recovery S1→S0 requires N_confirm consecutive samples.
 8. Missing signal holds current state.
 9. Hysteresis gap satisfies 3*sigma_T floor.
10. Proactive trigger exceeds 3*sigma_T_dot noise floor.

Timing strategy: all tests use a fixed ANCHOR_T (far in the past) for
last_switch_monotonic, and pass explicit now_monotonic values that are
always ANCHOR_T + dwell + N seconds. This avoids race conditions with
time.monotonic() advancing between test setup and assertion.

Run: pytest tests/test_thermal_scheduler.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "03_code"))

from scheduler.thermal_scheduler import (
    DEFAULT_SCHEDULER_CONFIG as CFG,
    DecisionReason,
    DvfsState,
    SchedulerState,
    decide,
)

# Fixed time anchor: last_switch happened long before any test call.
# All now_monotonic values passed to decide() are ANCHOR + dwell + margin,
# so the dwell guard is always cleared unless a test explicitly tests dwell.
ANCHOR_T = 1_000_000.0          # arbitrary large fixed monotonic value
POST_DWELL = ANCHOR_T + CFG.dwell_time_s + 5.0  # safely past dwell


def fresh(state: DvfsState = DvfsState.S0) -> SchedulerState:
    """SchedulerState with last_switch far in the past (dwell cleared)."""
    s = SchedulerState()
    s.current_state = state
    s.last_switch_monotonic = ANCHOR_T  # dwell clears when now > ANCHOR + dwell
    return s


def pump_confirm(s, T, T_dot, n=None, throttled_now=0):
    """
    Drive N_confirm-1 samples (CONFIRM_HOLD expected), then one final sample.
    Returns (final_state, final_reason).
    Each call uses POST_DWELL as now_monotonic so dwell is never active.
    After a state change inside this function, last_switch_monotonic is updated
    by decide(); subsequent calls still use POST_DWELL which is >> dwell window
    relative to ANCHOR_T, but NOT >> dwell relative to the new last_switch.
    So we space calls by dwell_time_s + 1 to simulate time passing.
    """
    n = n if n is not None else CFG.n_confirm
    state, reason = None, None
    for i in range(n):
        # Each sample is spaced dwell_time_s + 1s apart from the previous
        # so that a state-change in an earlier iteration doesn't re-trigger dwell.
        now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * (i + 1)
        state, reason = decide(
            T=T, T_dot=T_dot,
            throttled_now=throttled_now,
            sched_state=s,
            now_monotonic=now,
        )
    return state, reason


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------
def test_cold_start_is_S0():
    s = fresh()
    state, reason = decide(
        T=45.0, T_dot=0.1, throttled_now=0,
        sched_state=s, now_monotonic=POST_DWELL,
    )
    assert state == DvfsState.S0
    assert reason == DecisionReason.NO_CHANGE


# ---------------------------------------------------------------------------
# Test 2: reactive escalation requires exactly N_confirm samples
# ---------------------------------------------------------------------------
def test_reactive_escalation_requires_n_confirm():
    s = fresh()
    T = CFG.T_escalate_S0_to_S1 + 1.0

    # First N_confirm-1 samples: must stay at S0 with CONFIRM_HOLD
    for i in range(CFG.n_confirm - 1):
        now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * (i + 1)
        state, reason = decide(
            T=T, T_dot=0.1, throttled_now=0,
            sched_state=s, now_monotonic=now,
        )
        assert state == DvfsState.S0, f"premature switch at sample {i+1}"
        assert reason == DecisionReason.CONFIRM_HOLD, \
            f"expected CONFIRM_HOLD at sample {i+1}, got {reason}"

    # Nth sample: must switch to S1
    now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * CFG.n_confirm
    state, reason = decide(
        T=T, T_dot=0.1, throttled_now=0,
        sched_state=s, now_monotonic=now,
    )
    assert state == DvfsState.S1
    assert reason == DecisionReason.ESCALATE_REACTIVE


# ---------------------------------------------------------------------------
# Test 3: proactive escalation via T_dot
# ---------------------------------------------------------------------------
def test_proactive_escalation_via_T_dot():
    s = fresh()
    # T is in concern zone but BELOW reactive threshold
    T = CFG.T_dot_concern_floor + 1.0
    assert T < CFG.T_escalate_S0_to_S1, \
        f"test setup broken: T={T} must be < T_escalate={CFG.T_escalate_S0_to_S1}"

    for i in range(CFG.n_confirm - 1):
        now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * (i + 1)
        state, reason = decide(
            T=T, T_dot=CFG.T_dot_proactive + 0.1, throttled_now=0,
            sched_state=s, now_monotonic=now,
        )
        assert state == DvfsState.S0
        assert reason == DecisionReason.CONFIRM_HOLD

    now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * CFG.n_confirm
    state, reason = decide(
        T=T, T_dot=CFG.T_dot_proactive + 0.1, throttled_now=0,
        sched_state=s, now_monotonic=now,
    )
    assert state == DvfsState.S1
    assert reason == DecisionReason.ESCALATE_PROACTIVE


# ---------------------------------------------------------------------------
# Test 4: dwell blocks switching
# ---------------------------------------------------------------------------
def test_dwell_blocks_switching():
    s = fresh()
    # now_monotonic is WITHIN the dwell window
    now_in_dwell = ANCHOR_T + CFG.dwell_time_s * 0.5  # 50% into dwell
    state, reason = decide(
        T=CFG.T_escalate_S0_to_S1 + 5.0, T_dot=2.0, throttled_now=0,
        sched_state=s, now_monotonic=now_in_dwell,
    )
    assert state == DvfsState.S0
    assert reason == DecisionReason.DWELL_HOLD


# ---------------------------------------------------------------------------
# Test 5: no double-escalation (S0 → S1 only, even if T >> S1 threshold)
# ---------------------------------------------------------------------------
def test_no_double_escalation():
    s = fresh()
    T = CFG.T_escalate_S1_to_S2 + 5.0  # WAY above both thresholds

    # After N_confirm samples, state must be S1, not S2
    for i in range(CFG.n_confirm):
        now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * (i + 1)
        state, _ = decide(
            T=T, T_dot=2.0, throttled_now=0,
            sched_state=s, now_monotonic=now,
        )
    assert state == DvfsState.S1, \
        f"must stop at S1 after first escalation, got {state}"


# ---------------------------------------------------------------------------
# Test 6: recovery S2→S1
# ---------------------------------------------------------------------------
def test_recovery_S2_to_S1():
    s = fresh(state=DvfsState.S2)
    T = CFG.T_recover_S2_to_S1 - 1.0

    for i in range(CFG.n_confirm - 1):
        now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * (i + 1)
        state, reason = decide(
            T=T, T_dot=-0.1, throttled_now=0,
            sched_state=s, now_monotonic=now,
        )
        assert state == DvfsState.S2
        assert reason == DecisionReason.CONFIRM_HOLD

    now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * CFG.n_confirm
    state, reason = decide(
        T=T, T_dot=-0.1, throttled_now=0,
        sched_state=s, now_monotonic=now,
    )
    assert state == DvfsState.S1
    assert reason == DecisionReason.RECOVER


# ---------------------------------------------------------------------------
# Test 7: recovery S1→S0
# ---------------------------------------------------------------------------
def test_recovery_S1_to_S0():
    s = fresh(state=DvfsState.S1)
    T = CFG.T_recover_S1_to_S0 - 1.0

    for i in range(CFG.n_confirm - 1):
        now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * (i + 1)
        state, reason = decide(
            T=T, T_dot=-0.1, throttled_now=0,
            sched_state=s, now_monotonic=now,
        )
        assert state == DvfsState.S1
        assert reason == DecisionReason.CONFIRM_HOLD

    now = ANCHOR_T + (CFG.dwell_time_s + 1.0) * CFG.n_confirm
    state, reason = decide(
        T=T, T_dot=-0.1, throttled_now=0,
        sched_state=s, now_monotonic=now,
    )
    assert state == DvfsState.S0
    assert reason == DecisionReason.RECOVER


# ---------------------------------------------------------------------------
# Test 8: missing signal
# ---------------------------------------------------------------------------
def test_missing_signal_holds_state():
    s = fresh(state=DvfsState.S1)
    state, reason = decide(
        T=None, T_dot=None, throttled_now=None,
        sched_state=s, now_monotonic=POST_DWELL,
    )
    assert state == DvfsState.S1
    assert reason == DecisionReason.MISSING_SIGNAL


# ---------------------------------------------------------------------------
# Test 9: hysteresis floor
# ---------------------------------------------------------------------------
def test_hysteresis_gap_satisfied():
    min_gap = 3 * CFG.sigma_T
    s0s1_gap = CFG.T_escalate_S0_to_S1 - CFG.T_recover_S1_to_S0
    s1s2_gap = CFG.T_escalate_S1_to_S2 - CFG.T_recover_S2_to_S1
    assert s0s1_gap > min_gap, \
        f"S0/S1 gap {s0s1_gap:.2f}°C < 3σ_T={min_gap:.2f}°C"
    assert s1s2_gap > min_gap, \
        f"S1/S2 gap {s1s2_gap:.2f}°C < 3σ_T={min_gap:.2f}°C"


# ---------------------------------------------------------------------------
# Test 10: proactive trigger above noise floor
# ---------------------------------------------------------------------------
def test_proactive_trigger_above_noise_floor():
    assert CFG.T_dot_proactive > 3 * CFG.sigma_T_dot, (
        f"T_dot_proactive={CFG.T_dot_proactive} must exceed "
        f"3*sigma_T_dot={3*CFG.sigma_T_dot:.4f}"
    )