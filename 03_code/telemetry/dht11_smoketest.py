"""
DHT11 hardware sanity check.

Verifies the sensor is wired correctly and producing plausible readings
before we integrate ambient logging into telemetry_pipeline.

Usage:
    python3 03_code/telemetry/dht11_smoketest.py
    python3 03_code/telemetry/dht11_smoketest.py --pin 4 --reads 10

The DHT11 is a low-precision sensor (+/- 2 C temperature, 1 C
resolution, +/- 5 percent RH). It samples at 1 Hz max and requires
>= 2 s between reads. Failed reads are common; the script retries.
"""

import argparse
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pin", type=int, default=4,
                        help="BCM GPIO pin number (default: 4 = physical pin 7)")
    parser.add_argument("--reads", type=int, default=5,
                        help="Number of successful reads to collect")
    parser.add_argument("--interval", type=float, default=2.5,
                        help="Seconds between read attempts (>= 2.0)")
    parser.add_argument("--max-attempts", type=int, default=20,
                        help="Cap total attempts to avoid infinite loops")
    args = parser.parse_args()

    if args.interval < 2.0:
        parser.error("--interval must be >= 2.0 (DHT11 hardware limit)")

    try:
        import board
        import adafruit_dht
    except ImportError as e:
        print(f"FAIL: required library missing: {e}")
        print("Install with:")
        print("  sudo apt install -y libgpiod2")
        print("  pip install adafruit-circuitpython-dht --break-system-packages")
        sys.exit(2)

    # Map BCM pin number to board.Dx attribute.
    pin_attr = f"D{args.pin}"
    if not hasattr(board, pin_attr):
        print(f"FAIL: board has no attribute {pin_attr}; check pin number")
        sys.exit(2)
    pin_obj = getattr(board, pin_attr)

    print(f"DHT11 smoketest")
    print(f"  Pin (BCM)       : {args.pin}")
    print(f"  Target reads    : {args.reads}")
    print(f"  Interval        : {args.interval} s")
    print(f"  Max attempts    : {args.max_attempts}")
    print()

    # use_pulseio=False is more reliable on Pi 5.
    dht = adafruit_dht.DHT11(pin_obj, use_pulseio=False)

    successes = 0
    attempts = 0
    temps = []
    hums = []
    errors = 0

    while successes < args.reads and attempts < args.max_attempts:
        attempts += 1
        try:
            t_c = dht.temperature
            h = dht.humidity
            if t_c is None or h is None:
                print(f"  attempt {attempts}: read returned None")
                errors += 1
            else:
                successes += 1
                temps.append(t_c)
                hums.append(h)
                print(f"  attempt {attempts}: T={t_c:5.1f} C   RH={h:5.1f} %")
        except RuntimeError as e:
            # DHT11 commonly reports checksum errors; not fatal.
            print(f"  attempt {attempts}: RuntimeError: {e}")
            errors += 1
        except Exception as e:
            print(f"  attempt {attempts}: UNEXPECTED {type(e).__name__}: {e}")
            errors += 1

        if successes < args.reads and attempts < args.max_attempts:
            time.sleep(args.interval)

    try:
        dht.exit()
    except Exception:
        pass

    print()
    print(f"Results: {successes}/{attempts} successful, {errors} errors")
    if successes < args.reads:
        print("FAIL: insufficient successful reads. Check wiring:")
        print("  - VCC -> 3.3V (Pi physical pin 1)")
        print("  - GND -> GND (Pi physical pin 6)")
        print(f"  - DATA -> BCM pin {args.pin} (Pi physical pin 7 if BCM 4)")
        sys.exit(1)

    t_mean = sum(temps) / len(temps)
    h_mean = sum(hums) / len(hums)
    print(f"  Mean temp       : {t_mean:.1f} C")
    print(f"  Mean humidity   : {h_mean:.1f} %")

    if not (0.0 <= t_mean <= 50.0):
        print(f"WARN: mean temp {t_mean:.1f} outside DHT11 spec range 0-50 C")
    if not (0.0 <= h_mean <= 100.0):
        print(f"WARN: mean humidity {h_mean:.1f} outside 0-100 %")

    print()
    print("PASS: DHT11 producing plausible readings")
    sys.exit(0)


if __name__ == "__main__":
    main()