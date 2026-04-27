# Phase B.5 EMA Parameter Tuning Report

## Methodology

Swept alpha in [0.1, 0.15, 0.2, 0.25, 0.3] and derivative_stride in [3, 5, 7, 10]
(20 pairs total).

For each (alpha, stride) pair, computed across all calibration
runs:
- **Steady-state noise variance**: std dev of T_dot during
  idle plateau (last 5 min of idle runs) and stress soak
  (minutes 10-25 of stress runs).
- **Response lag (90% rise time)**: time from heating ramp
  start (t=10s, when stress-ng begins) to when T_dot reaches
  90% of its peak value. Standard control-systems metric for
  step response speed.
Selection criterion: minimize combined noise (mean of idle
and stress noise) subject to response lag <= 10.0s.

## Calibration Runs Used

| Run | Workload |
|-----|----------|
| 2026-04-25_234547_calib_idle_passive_run1 | idle |
| 2026-04-26_135357_calib_idle_passive_run2 | idle |
| 2026-04-26_151440_calib_stress_passive_run1 | stress |
| 2026-04-26_155639_calib_stress_passive_run2 | stress |

## Sweep Results (sorted by combined noise, ascending)

| alpha | stride | noise_idle | noise_stress | noise_combined | lag_heating_sec |
|-------|--------|------------|--------------|----------------|-----------------|
| 0.1 | 10 | 0.0677 | 0.0841 | 0.0759 | 10.000 |
| 0.1 | 7 | 0.0857 | 0.1081 | 0.0969 | 9.500 |
| 0.15 | 10 | 0.0934 | 0.1159 | 0.1046 | 9.900 |
| 0.1 | 5 | 0.1050 | 0.1335 | 0.1193 | 9.200 |
| 0.2 | 10 | 0.1150 | 0.1429 | 0.1289 | 9.900 |
| 0.15 | 7 | 0.1212 | 0.1532 | 0.1372 | 9.400 |
| 0.25 | 10 | 0.1337 | 0.1664 | 0.1501 | 9.900 |
| 0.1 | 3 | 0.1417 | 0.1790 | 0.1604 | 9.000 |
| 0.3 | 10 | 0.1503 | 0.1875 | 0.1689 | 9.800 |
| 0.15 | 5 | 0.1516 | 0.1931 | 0.1724 | 9.100 |
| 0.2 | 7 | 0.1527 | 0.1934 | 0.1730 | 9.400 |
| 0.25 | 7 | 0.1808 | 0.2295 | 0.2052 | 9.400 |
| 0.2 | 5 | 0.1946 | 0.2484 | 0.2215 | 9.100 |
| 0.3 | 7 | 0.2062 | 0.2623 | 0.2343 | 9.300 |
| 0.15 | 3 | 0.2096 | 0.2649 | 0.2372 | 8.800 |
| 0.25 | 5 | 0.2344 | 0.2997 | 0.2670 | 9.100 |
| 0.3 | 5 | 0.2714 | 0.3475 | 0.3095 | 9.000 |
| 0.2 | 3 | 0.2755 | 0.3483 | 0.3119 | 8.800 |
| 0.25 | 3 | 0.3395 | 0.4293 | 0.3844 | 8.700 |
| 0.3 | 3 | 0.4018 | 0.5079 | 0.4548 | 8.700 |

## Pareto Frontier

Pareto-optimal pairs (no other pair has both lower noise AND lower lag):

- alpha=0.25, stride=3 -> noise=0.3844, lag=8.700s
- alpha=0.15, stride=3 -> noise=0.2372, lag=8.800s
- alpha=0.1, stride=3 -> noise=0.1604, lag=9.000s
- alpha=0.1, stride=5 -> noise=0.1193, lag=9.200s
- alpha=0.1, stride=7 -> noise=0.0969, lag=9.500s
- alpha=0.1, stride=10 -> noise=0.0759, lag=10.000s

## Selected Configuration

**alpha = 0.1**
**derivative_stride = 10**

- Combined noise: 0.0759 C/s
- 90% rise time: 10.000 s
  (within 10.0s budget)

## Action Required (Manual)

Update `03_code/scheduler/derivatives.py` `DEFAULT_CONFIG_5HZ`:
```python
DEFAULT_CONFIG_5HZ = DerivativeConfig(
    alpha=0.1,
    derivative_stride=10,
    sampling_rate_hz=5.0,
)
```

Re-run `python tests/test_derivatives.py`. All 9 tests must pass.