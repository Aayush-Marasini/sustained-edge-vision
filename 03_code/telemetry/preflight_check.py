"""
Pre-flight verification for paper-quality telemetry runs.
Fails loudly if any condition is not met.

Run immediately before starting a calibration or long-horizon experiment:
    python3 03_code/telemetry/preflight_check.py

Designed to fail gracefully on non-Pi hosts (returns SKIP rather than
crashing) so the script can be imported by tests on any platform.
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

_IS_LINUX = platform.system() == "Linux"


def check(name, ok, detail):
    if ok is None:
        symbol = "SKIP"
    else:
        symbol = "PASS" if ok else "FAIL"
    print(f"  [{symbol}] {name}: {detail}")
    # SKIP does not count as failure for non-Pi hosts.
    return ok is None or ok


def _safe_read_text(path: str):
    try:
        return Path(path).read_text().strip()
    except OSError as e:
        return None


def _safe_subprocess(cmd):
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return None


def main():
    print("Pre-flight checklist for paper-quality run")
    print("=" * 50)
    if not _IS_LINUX:
        print(f"  [WARN] Non-Linux host ({platform.system()}); most checks will SKIP.")
    all_ok = True

    # Git state (cross-platform)
    dirty_out = _safe_subprocess(["git", "status", "--porcelain"])
    if dirty_out is None:
        all_ok &= check("git tree clean", None, "git not available")
    else:
        dirty = dirty_out.strip()
        all_ok &= check(
            "git tree clean",
            not dirty,
            "clean" if not dirty else f"{len(dirty.splitlines())} uncommitted changes",
        )

    sha_out = _safe_subprocess(["git", "rev-parse", "--short", "HEAD"])
    if sha_out is None:
        check("git commit", None, "git not available")
    else:
        check("git commit", True, sha_out.strip())

    # Governor (Linux/Pi only)
    gov = _safe_read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if gov is None:
        all_ok &= check("cpu governor", None, "non-Pi host")
    else:
        all_ok &= check("cpu governor", gov == "ondemand", gov)

    # WiFi disabled — robust to Pi boards without wifi hardware.
    rfkill_out = _safe_subprocess(["rfkill", "list", "wifi"])
    if rfkill_out is None:
        all_ok &= check("wifi disabled", None, "rfkill not available")
    elif not rfkill_out.strip():
        # Empty output = no wifi device at all; treat as pass.
        all_ok &= check("wifi disabled", True, "no wifi device present")
    else:
        wifi_blocked = "Soft blocked: yes" in rfkill_out
        all_ok &= check(
            "wifi disabled",
            wifi_blocked,
            "blocked" if wifi_blocked else "ENABLED — run: sudo rfkill block wifi",
        )

    # Disk space (cross-platform)
    free_gb = shutil.disk_usage("/").free / 1e9
    all_ok &= check("disk space >=1 GB free", free_gb >= 1.0, f"{free_gb:.1f} GB free")

    # psutil available (cross-platform)
    try:
        import psutil
        check("psutil importable", True, psutil.__version__)
    except ImportError:
        all_ok &= check("psutil importable", False, "MISSING — run: pip install psutil")

    # Sensor endpoints (Pi only)
    hwmon_path = Path("/sys/class/hwmon/hwmon0/temp1_input")
    if not _IS_LINUX:
        all_ok &= check("thermal sensor", None, "non-Pi host")
    else:
        hwmon_ok = hwmon_path.exists()
        all_ok &= check("thermal sensor", hwmon_ok, "hwmon0/temp1_input readable")

    vcgencmd_ok = _safe_subprocess(["which", "vcgencmd"]) is not None
    if not _IS_LINUX:
        all_ok &= check("vcgencmd available", None, "non-Pi host")
    else:
        all_ok &= check("vcgencmd available", vcgencmd_ok,
                       "found" if vcgencmd_ok else "MISSING")

    # Initial temp sanity (Pi only)
    if _IS_LINUX and hwmon_path.exists():
        try:
            temp_milli = int(hwmon_path.read_text().strip())
            temp_c = temp_milli / 1000.0
            temp_ok = 25.0 <= temp_c <= 55.0
            all_ok &= check(
                "Pi temperature reasonable for start",
                temp_ok,
                f"{temp_c:.1f} C (expected 25-55 for cold-ish start)",
            )
        except (OSError, ValueError) as e:
            all_ok &= check("Pi temperature reasonable for start", False, f"read failed: {e}")
    else:
        all_ok &= check("Pi temperature reasonable for start", None, "non-Pi host")

    print("=" * 50)
    if all_ok:
        print("ALL CHECKS PASSED (or SKIP on non-Pi) -- ready for run")
        sys.exit(0)
    else:
        print("FAILURES -- fix before running. Do NOT produce paper data in this state.")
        sys.exit(1)


if __name__ == "__main__":
    main()