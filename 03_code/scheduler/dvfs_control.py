"""
dvfs_control.py
===============
DVFS state primitive: read, set, restore Pi 5 scaling_max_freq.

Design contract
---------------
- Single source of truth for the {S0, S1, S2} action space defined in
  EXPERIMENTAL_PROTOCOL.md and CHANGELOG v0.7.11.
- Writes to /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq.
  Requires root (run script with sudo, or call from a sudo'd parent).
- Governor is NEVER touched. The deployment scenario (per
  proposal_v2.pdf §1) requires `ondemand` to remain active.
- ALWAYS reset cap to 2400000 kHz at end of any paper-quality run.
  The CLI `--restore` command is the canonical way to do this.

WorkPlan grounding
------------------
- Task 9 (§6.1): defines configuration space; this module *implements* it.
- Task 12 (§6.4): scheduler decision policy will import set_state_by_name().

Usage (CLI)
-----------
    sudo python dvfs_control.py --status
    sudo python dvfs_control.py --set-state S1
    sudo python dvfs_control.py --restore
    sudo python dvfs_control.py --list

Usage (library)
---------------
    from scheduler.dvfs_control import (
        set_state_by_name, restore_max, get_current_cap_khz, STATES
    )

    set_state_by_name("S1")           # cap to 1800000 kHz on every CPU
    cap = get_current_cap_khz()       # returns dict cpu0..cpuN
    restore_max()                     # cap to 2400000 kHz on every CPU
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# -----------------------------------------------------------------------------
# Action space (locked per CHANGELOG v0.7.11 / EXPERIMENTAL_PROTOCOL.md)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class DvfsState:
    name: str
    cap_khz: int
    expected_fps: float
    purpose: str

STATES: Dict[str, DvfsState] = {
    "S0": DvfsState("S0", 2_400_000, 14.58, "Max performance (default)"),
    "S1": DvfsState("S1", 1_800_000, 12.43, "Moderate cooling"),
    "S2": DvfsState("S2", 1_500_000, 11.01, "Aggressive cooling (min)"),
}

MAX_CAP_KHZ = 2_400_000  # canonical reset value

# -----------------------------------------------------------------------------
# Sysfs paths
# -----------------------------------------------------------------------------

_CPUFREQ_GLOB        = "/sys/devices/system/cpu/cpu[0-9]*/cpufreq"
_SCALING_MAX_NAME    = "scaling_max_freq"
_SCALING_GOV_NAME    = "scaling_governor"
_AVAILABLE_FREQ_NAME = "scaling_available_frequencies"

# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------

class DvfsError(RuntimeError):
    """Raised on any DVFS read/write failure."""


# -----------------------------------------------------------------------------
# Discovery
# -----------------------------------------------------------------------------

def _cpufreq_dirs() -> List[Path]:
    dirs = sorted(Path(p) for p in glob.glob(_CPUFREQ_GLOB))
    if not dirs:
        raise DvfsError(
            f"No cpufreq directories found under {_CPUFREQ_GLOB}. "
            "Are you on a Pi with cpufreq enabled?"
        )
    return dirs


def list_available_freqs_khz() -> List[int]:
    """Return sorted list of allowed scaling frequencies (kHz) from cpu0."""
    path = _cpufreq_dirs()[0] / _AVAILABLE_FREQ_NAME
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise DvfsError(f"Cannot read {path}: {e}")
    return sorted(int(tok) for tok in raw.split() if tok.strip())


# -----------------------------------------------------------------------------
# Read
# -----------------------------------------------------------------------------

def get_current_cap_khz() -> Dict[str, int]:
    """Return mapping {cpu_name: scaling_max_freq_khz} for every CPU."""
    out: Dict[str, int] = {}
    for d in _cpufreq_dirs():
        path = d / _SCALING_MAX_NAME
        try:
            out[d.parent.name] = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as e:
            raise DvfsError(f"Cannot read {path}: {e}")
    return out


def get_governor() -> str:
    """Return scaling_governor of cpu0 (assumed identical across cores)."""
    path = _cpufreq_dirs()[0] / _SCALING_GOV_NAME
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise DvfsError(f"Cannot read {path}: {e}")


# -----------------------------------------------------------------------------
# Write
# -----------------------------------------------------------------------------

def _write_cap_one(path: Path, cap_khz: int) -> None:
    try:
        with path.open("w", encoding="utf-8") as f:
            f.write(str(cap_khz))
    except PermissionError:
        raise DvfsError(
            f"Permission denied writing {path}. "
            "Re-run this script under sudo: `sudo python dvfs_control.py ...`"
        )
    except OSError as e:
        raise DvfsError(f"OS error writing {path}: {e}")


def set_cap_khz(cap_khz: int, *, verify: bool = True,
                verify_settle_s: float = 0.1) -> Dict[str, int]:
    """Set scaling_max_freq on every CPU to `cap_khz`. Optionally verify."""
    available = list_available_freqs_khz()
    if cap_khz not in available:
        raise DvfsError(
            f"Requested cap {cap_khz} kHz not in available frequencies: "
            f"{available}"
        )

    for d in _cpufreq_dirs():
        _write_cap_one(d / _SCALING_MAX_NAME, cap_khz)

    if verify:
        time.sleep(verify_settle_s)  # brief settle before readback
        post = get_current_cap_khz()
        bad = {cpu: v for cpu, v in post.items() if v != cap_khz}
        if bad:
            raise DvfsError(
                f"DVFS write verification FAILED. Wrote {cap_khz} but "
                f"these CPUs report different caps: {bad}"
            )
        return post
    return get_current_cap_khz()


def set_state_by_name(state_name: str, **kwargs) -> Dict[str, int]:
    """Apply a named state from STATES dict, e.g. 'S0', 'S1', 'S2'."""
    if state_name not in STATES:
        raise DvfsError(
            f"Unknown state '{state_name}'. Valid: {list(STATES.keys())}"
        )
    return set_cap_khz(STATES[state_name].cap_khz, **kwargs)


def restore_max(**kwargs) -> Dict[str, int]:
    """Reset scaling_max_freq to MAX_CAP_KHZ (= S0)."""
    return set_cap_khz(MAX_CAP_KHZ, **kwargs)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _print_status() -> None:
    info = {
        "governor":          get_governor(),
        "available_freqs":   list_available_freqs_khz(),
        "current_cap_khz":   get_current_cap_khz(),
        "named_states":      {k: v.cap_khz for k, v in STATES.items()},
    }
    print(json.dumps(info, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(description="Pi 5 DVFS control utility.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status",     action="store_true",
                   help="Print governor, allowed freqs, and current cap.")
    g.add_argument("--list",       action="store_true",
                   help="List allowed scaling frequencies (kHz).")
    g.add_argument("--set",        type=int, metavar="KHZ",
                   help="Set scaling_max_freq to a raw kHz value.")
    g.add_argument("--set-state",  type=str, metavar="NAME",
                   help="Set to a named state (S0, S1, S2).")
    g.add_argument("--restore",    action="store_true",
                   help="Reset cap to 2400000 kHz (S0).")
    args = p.parse_args()

    try:
        if args.status:
            _print_status()
        elif args.list:
            print(" ".join(str(f) for f in list_available_freqs_khz()))
        elif args.set is not None:
            after = set_cap_khz(args.set)
            print(json.dumps({"status": "ok", "current_cap_khz": after}, indent=2))
        elif args.set_state is not None:
            after = set_state_by_name(args.set_state)
            print(json.dumps({
                "status": "ok",
                "state":  args.set_state,
                "current_cap_khz": after,
            }, indent=2))
        elif args.restore:
            after = restore_max()
            print(json.dumps({"status": "restored", "current_cap_khz": after}, indent=2))
    except DvfsError as e:
        print(f"DVFS ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e!r}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())