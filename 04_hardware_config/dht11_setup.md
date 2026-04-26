# DHT11 Ambient Sensor — Setup and Verification

## Hardware

| Component | Value |
|-----------|-------|
| Sensor | DHT11 3-pin breakout board |
| Accuracy | ±2 °C temperature, ±5% RH |
| Resolution | 1 °C temperature, 1% RH |
| Sample rate | ≤ 1 Hz (≥ 2s between reads) |
| Operating range | 0–50 °C, 20–90% RH |

## Wiring (Pi 5)

| DHT11 pin | Pi physical pin | Pi function |
|-----------|-----------------|-------------|
| VCC / + | Pin 1 | 3.3V |
| DATA / OUT | Pin 7 | GPIO4 (BCM 4) |
| GND / – | Pin 6 | GND |

Pull-up resistor: built into the 3-pin breakout board (not needed externally).

## Software Stack

Tested on Pi OS Debian Trixie, Python 3.13, inside `yolov8_env` virtualenv.

```bash
sudo apt install -y liblgpio-dev swig python3-dev
pip install lgpio --break-system-packages
pip install adafruit-circuitpython-dht --break-system-packages
```

Verify:
```bash
python -c "import lgpio; import board; import adafruit_dht; print('OK')"
```

## Smoketest Results

Run date: 2026-04-25
Script: `03_code/telemetry/dht11_smoketest.py`

Results: 5/5 successful, 0 errors
Mean temp       : 22.3 C
Mean humidity   : 61.0 %
PASS: DHT11 producing plausible readings

## Integration

DHT11 readings are logged at run start and run end via `--dht11-pin 4` flag.
Output lands in `run_metadata.json` under `ambient_dht11_start` and
`ambient_dht11_end`. Values are for reproducibility logging only.
**Must not feed into the scheduler state vector.**

## Integration Test Results

| Run | Samples | Completeness | DHT11 start | DHT11 end |
|-----|---------|--------------|-------------|-----------|
| v1 (pre-fix) | 288/300 | 0.960 | 22.3 °C / 62% RH | 22.3 °C / 62% RH |
| v2 (timeout fix) | 288/299 | 0.963 | 22.3 °C / 62% RH | 22.2 °C / 62% RH |
| v3 (busy-wait) | 288/299 | 0.963 | 22.3 °C / 62% RH | — |
| v4 (thread fix) | 300/299 | 1.003 | 22.4 °C / 61.3% RH | 22.6 °C / 60.7% RH |

v4 is the production-ready configuration.