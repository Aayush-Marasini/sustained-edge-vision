"""
End-to-end smoke test: feed mock telemetry samples into the scheduler
runtime and verify both output CSVs are produced correctly.
Runs in the container without Pi hardware.
"""

import csv
import multiprocessing as mp
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_code"))

from scheduler.scheduler_runtime import SchedulerRuntime


def main():
    run_dir = Path("/tmp/scheduler_e2e_test")
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    q = mp.Queue(maxsize=100)
    # Test-only: pass a synthetic shared_start_monotonic so the
    # boot-decision row exercises the aligned-offset code path.
    test_start = time.monotonic()
    sched = SchedulerRuntime(
        run_dir=str(run_dir),
        telemetry_queue=q,
        shared_start_monotonic=test_start,
    )
    sched.start()

    # Feed 50 mock samples simulating a thermal ramp.
    start = time.monotonic()
    for i in range(50):
        temp = 50.0 + i * 0.3  # rising temperature
        util = 80.0 + (i % 3)  # bursty CPU
        volt = 0.85 - (0.001 if i > 30 else 0.0)  # small sag late in run
        sample = {
            "monotonic_offset_s": round(time.monotonic() - start, 4),
            "utc_timestamp": datetime.now(timezone.utc).isoformat(),
            "temp_soc_c": temp,
            "volt_core_v": volt,
            "cpu_util_percent": util,
            "mem_util_percent": 40.0,
            "cpu_freq_mhz": 2400.0,
            "throttle_raw": 0,
            "throttled_now": 0,
            "undervolt_now": 0,
        }
        q.put(sample)
        time.sleep(0.02)  # simulate 50 Hz feed (faster than prod for test speed)

    time.sleep(1.0)  # let scheduler drain
    sched.stop()

    # Verify outputs
    derived_csv = run_dir / "telemetry_derived.csv"
    decisions_csv = run_dir / "scheduler_decisions.csv"

    assert derived_csv.exists(), f"derived CSV missing at {derived_csv}"
    assert decisions_csv.exists(), f"decisions CSV missing at {decisions_csv}"

    with open(derived_csv) as f:
        rows = list(csv.DictReader(f))
    print(f"telemetry_derived.csv: {len(rows)} rows")
    print("Last row (showing state vector is being computed):")
    for k, v in rows[-1].items():
        print(f"  {k:10s} = {v}")

    with open(decisions_csv) as f:
        decisions = list(csv.DictReader(f))
    print(f"\nscheduler_decisions.csv: {len(decisions)} rows")
    for d in decisions:
        print(f"  t={d['monotonic_offset_s']}s reason={d['reason']} "
              f"config={d['config_resolution']}/{d['config_precision']}/{d['config_fps_cap']}")

    # Basic correctness: T_dot should be positive (we fed a rising ramp).
    # Find a row where T_dot is populated.
    for r in rows[-5:]:
        if r.get("T_dot") not in ("", None):
            t_dot = float(r["T_dot"])
            print(f"\nFinal T_dot = {t_dot:+.3f} C/s (expected positive, fed rising ramp)")
            assert t_dot > 0, f"expected rising T_dot, got {t_dot}"
            break

    print("\nEnd-to-end test PASSED")


if __name__ == "__main__":
    main()