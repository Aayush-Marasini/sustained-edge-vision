"""
Basic unit tests for derivatives.SignalEstimator and StateVectorBuilder.
These are container-runnable (no Pi hardware needed).

Run with:  python -m pytest tests/test_derivatives.py -v
or simply: python tests/test_derivatives.py
"""

import math
import sys
from pathlib import Path

# Make the scheduler package importable when running standalone.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_code"))

from scheduler.derivatives import SignalEstimator, StateVectorBuilder


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def test_ema_constant_signal_converges():
    est = SignalEstimator(alpha=0.2, derivative_stride=5, dt=0.2)
    for _ in range(50):
        s, r = est.update(70.0)
    assert approx(s, 70.0), f"EMA should converge to constant, got {s}"


def test_derivative_of_linear_ramp():
    # A signal rising by 0.5 units per sample at dt=0.2 -> true rate 2.5 /s
    est = SignalEstimator(alpha=1.0, derivative_stride=5, dt=0.2)  # alpha=1 -> no smoothing
    s, r = None, None
    for i in range(20):
        s, r = est.update(float(i) * 0.5)
    assert r is not None, "rate should be available after enough samples"
    assert approx(r, 2.5, tol=0.01), f"expected rate 2.5 /s, got {r}"


def test_derivative_is_none_until_history_full():
    est = SignalEstimator(alpha=0.5, derivative_stride=5, dt=0.2)
    # history_maxlen = stride + 1 = 6
    for i in range(5):
        _, r = est.update(float(i))
        assert r is None, f"rate should be None at sample {i}, got {r}"
    _, r = est.update(5.0)
    assert r is not None, "rate should become available once history is full"


def test_none_sample_does_not_crash():
    est = SignalEstimator(alpha=0.2, derivative_stride=5, dt=0.2)
    s, r = est.update(None)
    assert s is None and r is None
    # Valid value after None
    s, r = est.update(50.0)
    assert s == 50.0


def test_nan_sample_does_not_poison_ema():
    est = SignalEstimator(alpha=0.2, derivative_stride=5, dt=0.2)
    for _ in range(20):
        est.update(70.0)  # converge
    s_before, _ = est.update(70.0)
    s_after, _ = est.update(float("nan"))
    # NaN should carry forward, not poison
    assert approx(s_after, s_before), f"NaN poisoned EMA: {s_before} -> {s_after}"


def test_state_vector_builder_shape():
    builder = StateVectorBuilder()
    raw = {
        "temp_soc_c": 55.0,
        "cpu_util_percent": 30.0,
        "volt_core_v": 0.85,
        "cpu_freq_mhz": 2400.0,
        "mem_util_percent": 40.0,
    }
    state = builder.update(raw)
    # Formal state vector keys must all be present.
    for key in ("T", "T_dot", "U", "U_dot", "V", "V_dot"):
        assert key in state, f"missing state vector key {key}"
    # Rates are None on the first sample.
    assert state["T_dot"] is None
    assert state["T"] == 55.0  # first sample sets smoothed to raw


def test_state_vector_builder_accepts_both_column_forms():
    builder = StateVectorBuilder()
    internal = builder.update({"temp_soc": 55.0, "cpu_util": 30.0, "volt_core": 0.85,
                               "cpu_freq": 2400.0, "mem_util": 40.0})
    builder2 = StateVectorBuilder()
    csv_form = builder2.update({"temp_soc_c": 55.0, "cpu_util_percent": 30.0,
                                "volt_core_v": 0.85, "cpu_freq_mhz": 2400.0,
                                "mem_util_percent": 40.0})
    assert internal["T"] == csv_form["T"]


def test_invalid_alpha_raises():
    try:
        SignalEstimator(alpha=0.0, derivative_stride=5, dt=0.2)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for alpha=0")

    try:
        SignalEstimator(alpha=1.5, derivative_stride=5, dt=0.2)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for alpha>1")

def test_ema_step_response_matches_documented_time_constant():
    """
    Verify the docstring claim: tau ~= dt * (1 - alpha) / alpha.
    Feed a step input and check that the smoothed signal reaches
    (1 - 1/e) ~= 63.2% of the step within tau seconds.
    """
    alpha = 0.20
    dt = 0.2
    est = SignalEstimator(alpha=alpha, derivative_stride=5, dt=dt)
    # Initialize at 0
    est.update(0.0)
    # Documented time constant.
    tau = dt * (1.0 - alpha) / alpha  # = 0.8 s for alpha=0.20, dt=0.2
    n_samples_to_tau = int(round(tau / dt))  # 4 samples after the step
    # Apply step of magnitude 100.
    step_value = 100.0
    smoothed = None
    for _ in range(n_samples_to_tau):
        smoothed, _ = est.update(step_value)
    # Allow generous tolerance (geometric series vs continuous-time
    # exponential differ slightly at small sample counts).
    assert smoothed is not None
    assert 0.50 * step_value < smoothed < 0.75 * step_value, (
        f"EMA step response at t=tau should be near 63%, got {smoothed:.1f}"
    )

if __name__ == "__main__":
    tests = [
        ("ema_constant_signal_converges", test_ema_constant_signal_converges),
        ("derivative_of_linear_ramp", test_derivative_of_linear_ramp),
        ("derivative_is_none_until_history_full", test_derivative_is_none_until_history_full),
        ("none_sample_does_not_crash", test_none_sample_does_not_crash),
        ("nan_sample_does_not_poison_ema", test_nan_sample_does_not_poison_ema),
        ("state_vector_builder_shape", test_state_vector_builder_shape),
        ("state_vector_builder_accepts_both_column_forms", test_state_vector_builder_accepts_both_column_forms),
        ("invalid_alpha_raises", test_invalid_alpha_raises),
        ("ema_step_response_matches_documented_time_constant",
         test_ema_step_response_matches_documented_time_constant),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)