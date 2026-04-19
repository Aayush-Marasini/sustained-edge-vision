"""
telemetry_pipeline.py

Collects 6 hardware signals at 5 Hz from Raspberry Pi 5:
  - T_soc: SoC temperature (°C)
  - V_core: Core voltage (V)
  - U_cpu: Aggregate CPU utilization (%)
  - throttle: Throttle flag (0/1)
  - cpu_freq: ARM clock frequency (MHz)
  - mem_util: Memory utilization (%)

Runs as a subprocess, writes to CSV + JSON metadata sidecar.
Designed for minimal CPU overhead (<1%).

Usage:
  from telemetry_pipeline import TelemetryPipeline
  pipe = TelemetryPipeline(run_dir="/path/to/run", duration_sec=600)
  pipe.start()
  # ... do inference ...
  pipe.stop()
"""

import os
import sys
import time
import json
import csv
import signal
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import multiprocessing as mp


class TelemetryPipeline:
    """
    Collects hardware telemetry in a subprocess.
    
    Non-blocking: spawns worker process, returns immediately.
    Data written to disk asynchronously.
    """
    
    def __init__(
        self,
        run_dir,
        sampling_rate_hz=5,
        duration_sec=None,
        ambient_temp_c=None,
        cooling_condition="unknown",
        tags=None,
    ):
        """
        Args:
            run_dir: Directory where CSV and JSON are written
            sampling_rate_hz: Target sampling rate (default 5 Hz)
            duration_sec: Max duration; None = run until stop() called
            ambient_temp_c: Ambient temperature for metadata
            cooling_condition: "passive" or "active" for metadata
            tags: Dict of arbitrary metadata tags
        """
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        self.sampling_rate_hz = sampling_rate_hz
        self.sample_interval = 1.0 / sampling_rate_hz
        self.duration_sec = duration_sec
        self.ambient_temp_c = ambient_temp_c or 25.0
        self.cooling_condition = cooling_condition
        self.tags = tags or {}
        
        self.csv_path = self.run_dir / "telemetry_raw.csv"
        self.metadata_path = self.run_dir / "run_metadata.json"
        
        self._process = None
        self._stop_event = None
        self._start_time_monotonic = None
        self._start_time_utc = None
    
    def start(self):
        """Spawn telemetry subprocess."""
        self._stop_event = mp.Event()
        self._start_time_monotonic = time.monotonic()
        self._start_time_utc = datetime.now(timezone.utc).isoformat()
        
        self._process = mp.Process(
            target=_telemetry_worker,
            args=(
                self.csv_path,
                self.metadata_path,
                self.sampling_rate_hz,
                self.duration_sec,
                self._stop_event,
                self._start_time_monotonic,
                self._start_time_utc,
                self.ambient_temp_c,
                self.cooling_condition,
                self.tags,
            ),
        )
        self._process.start()
    
    def stop(self):
        """Stop the telemetry subprocess gracefully."""
        if self._process is None:
            return
        
        self._stop_event.set()
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.kill()


def _telemetry_worker(
    csv_path,
    metadata_path,
    sampling_rate_hz,
    duration_sec,
    stop_event,
    start_time_monotonic,
    start_time_utc,
    ambient_temp_c,
    cooling_condition,
    tags,
):
    """
    Worker process: samples signals and writes to CSV.
    
    Runs in a separate process to minimize blocking on main thread.
    """
    
    # Signal handlers for graceful shutdown
    def handle_signal(signum, frame):
        stop_event.set()
    
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    # Collect metadata before sampling
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(csv_path).parent.parent.parent,
            text=True,
        ).strip()
    except:
        git_sha = "unknown"
    
    try:
        hostname = subprocess.check_output(["hostname"], text=True).strip()
    except:
        hostname = "unknown"
    
    # Open CSV for writing
    fieldnames = [
        "monotonic_offset_s",
        "utc_timestamp",
        "temp_soc_c",
        "volt_core_v",
        "cpu_util_percent",
        "throttled",
        "cpu_freq_mhz",
        "mem_util_percent",
    ]
    
    csv_file = open(csv_path, "w", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()
    csv_file.flush()
    
    sample_interval = 1.0 / sampling_rate_hz
    sample_count = 0
    
    try:
        while not stop_event.is_set():
            # Check duration
            if duration_sec is not None:
                elapsed = time.monotonic() - start_time_monotonic
                if elapsed >= duration_sec:
                    break
            
            # Collect all signals
            sample_time = time.monotonic()
            utc_now = datetime.now(timezone.utc).isoformat()
            
            signals = _read_signals()
            
            # Write row
            row = {
                "monotonic_offset_s": sample_time - start_time_monotonic,
                "utc_timestamp": utc_now,
                "temp_soc_c": signals["temp_soc"],
                "volt_core_v": signals["volt_core"],
                "cpu_util_percent": signals["cpu_util"],
                "throttled": signals["throttled"],
                "cpu_freq_mhz": signals["cpu_freq"],
                "mem_util_percent": signals["mem_util"],
            }
            writer.writerow(row)
            
            # Flush periodically (every 10 samples = 2 seconds at 5 Hz)
            sample_count += 1
            if sample_count % 10 == 0:
                csv_file.flush()
            
            # Sleep until next sample
            elapsed_this_iteration = time.monotonic() - sample_time
            sleep_time = sample_interval - elapsed_this_iteration
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    finally:
        csv_file.close()
        
        # Write metadata sidecar
        metadata = {
            "git_sha": git_sha,
            "hostname": hostname,
            "start_time_utc": start_time_utc,
            "end_time_utc": datetime.now(timezone.utc).isoformat(),
            "sampling_rate_hz": sampling_rate_hz,
            "samples_collected": sample_count,
            "ambient_temp_c": ambient_temp_c,
            "cooling_condition": cooling_condition,
            "tags": tags,
        }
        
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)


def _read_signals():
    """
    Read all six signals from hardware endpoints.
    Returns dict with keys: temp_soc, volt_core, cpu_util, throttled, cpu_freq, mem_util
    """
    signals = {}
    
    # Temperature from hwmon0 (cpu_thermal)
    try:
        with open("/sys/class/hwmon/hwmon0/temp1_input") as f:
            temp_millidegrees = int(f.read().strip())
            signals["temp_soc"] = temp_millidegrees / 1000.0
    except:
        signals["temp_soc"] = 0.0
    
    # Voltage from vcgencmd
    try:
        output = subprocess.check_output(
            ["vcgencmd", "measure_volts", "core"],
            text=True,
        ).strip()
        # Format: "volt=0.7500V"
        volt_str = output.split("=")[1].rstrip("V")
        signals["volt_core"] = float(volt_str)
    except:
        signals["volt_core"] = 0.0
    
    # CPU utilization (aggregate across all cores)
    try:
        import psutil
        signals["cpu_util"] = psutil.cpu_percent(interval=None)
    except:
        signals["cpu_util"] = 0.0
    
    # Throttle flag from vcgencmd
    try:
        output = subprocess.check_output(
            ["vcgencmd", "get_throttled"],
            text=True,
        ).strip()
        # Format: "throttled=0x0"
        throttle_hex = output.split("=")[1]
        throttle_int = int(throttle_hex, 16)
        # Bit 0 = currently throttled, bit 2 = has throttled
        signals["throttled"] = 1 if (throttle_int & 0x1) else 0
    except:
        signals["throttled"] = 0
    
    # CPU frequency from vcgencmd
    try:
        output = subprocess.check_output(
            ["vcgencmd", "measure_clock", "arm"],
            text=True,
        ).strip()
        # Format: "frequency(0)=1500019456"
        freq_hz = int(output.split("=")[1])
        signals["cpu_freq"] = freq_hz / 1e6  # Convert to MHz
    except:
        signals["cpu_freq"] = 0.0
    
    # Memory utilization
    try:
        import psutil
        mem = psutil.virtual_memory()
        signals["mem_util"] = mem.percent
    except:
        signals["mem_util"] = 0.0
    
    return signals


if __name__ == "__main__":
    # Test: run for 30 seconds
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Testing telemetry pipeline in {tmpdir}")
        pipe = TelemetryPipeline(
            run_dir=tmpdir,
            sampling_rate_hz=5,
            duration_sec=30,
            ambient_temp_c=25,
            cooling_condition="passive",
        )
        pipe.start()
        print("Pipeline started. Collecting for 30 seconds...")
        time.sleep(30)
        pipe.stop()
        
        # Read and print CSV
        csv_file = Path(tmpdir) / "telemetry_raw.csv"
        if csv_file.exists():
            with open(csv_file) as f:
                lines = f.readlines()
            print(f"\nCollected {len(lines) - 1} samples (header + {len(lines) - 1} data rows)")
            print("First 5 rows:")
            for line in lines[:6]:
                print(line.rstrip())
        
        # Print metadata
        metadata_file = Path(tmpdir) / "run_metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)
            print("\nMetadata:")
            print(json.dumps(metadata, indent=2))