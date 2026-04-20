"""
Pre-flight verification for paper-quality telemetry runs.
Fails loudly if any condition is not met.

Run immediately before starting a calibration or long-horizon experiment:
    python3 03_code/telemetry/preflight_check.py
"""

import subprocess
import sys
from pathlib import Path


def check(name, ok, detail):
    symbol = "PASS" if ok else "FAIL"
    print(f"  [{symbol}] {name}: {detail}")
    return ok


def main():
    print("Pre-flight checklist for paper-quality run")
    print("=" * 50)
    all_ok = True

    # Git state
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], text=True
    ).strip()
    all_ok &= check(
        "git tree clean",
        not dirty,
        "clean" if not dirty else f"{len(dirty.splitlines())} uncommitted changes",
    )

    sha = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    check("git commit", True, sha)

    # Governor
    gov = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    all_ok &= check("cpu governor", gov == "ondemand", gov)

    # WiFi disabled
    try:
        rfkill = subprocess.check_output(["rfkill", "list", "wifi"], text=True)
        wifi_blocked = "Soft blocked: yes" in rfkill
    except FileNotFoundError:
        wifi_blocked = False
    all_ok &= check(
        "wifi disabled",
        wifi_blocked,
        "blocked" if wifi_blocked else "ENABLED — run: sudo rfkill block wifi",
    )

    # Disk space (need at least 500 MB for a 60-min run, plenty of headroom)
    import shutil
    free_gb = shutil.disk_usage("/").free / 1e9
    all_ok &= check("disk space >=1 GB free", free_gb >= 1.0, f"{free_gb:.1f} GB free")

    # psutil available
    try:
        import psutil
        check("psutil importable", True, psutil.__version__)
    except ImportError:
        all_ok &= check("psutil importable", False, "MISSING — run: pip install psutil")

    # Sensor endpoints exist
    hwmon_ok = Path("/sys/class/hwmon/hwmon0/temp1_input").exists()
    all_ok &= check("thermal sensor", hwmon_ok, "hwmon0/temp1_input readable")

    vcgencmd_ok = subprocess.run(
        ["which", "vcgencmd"], capture_output=True
    ).returncode == 0
    all_ok &= check("vcgencmd available", vcgencmd_ok, "found" if vcgencmd_ok else "MISSING")

    # Initial temp sanity
    temp_milli = int(Path("/sys/class/hwmon/hwmon0/temp1_input").read_text().strip())
    temp_c = temp_milli / 1000.0
    temp_ok = 25.0 <= temp_c <= 55.0
    all_ok &= check(
        "Pi temperature reasonable for start",
        temp_ok,
        f"{temp_c:.1f} °C (expected 25–55 for cold-ish start)",
    )

    print("=" * 50)
    if all_ok:
        print("ALL CHECKS PASSED — ready for paper-quality run")
        sys.exit(0)
    else:
        print("FAILURES — fix before running. Do NOT produce paper data in this state.")
        sys.exit(1)


if __name__ == "__main__":
    main()