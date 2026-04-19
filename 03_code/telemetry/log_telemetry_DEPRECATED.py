import time
import csv
import psutil
import subprocess
from datetime import datetime, timezone

def get_temp():
    # Reads temperature from vcgencmd
    res = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True)
    # Output format: temp=45.0'C
    return float(res.stdout.replace("temp=", "").replace("'C\n", ""))

def get_throttle_state():
    # Reads throttle flags (hex value)
    res = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True)
    return res.stdout.strip()

def get_fan_rpm():
    # You may need to change hwmon2 to hwmon1 or hwmon3 based on your Pi's sysfs tree
    try:
        with open('/sys/class/hwmon/hwmon2/fan1_input', 'r') as f:
            return int(f.read().strip())
    except FileNotFoundError:
        return 0

def main():
    log_file = f"telemetry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    with open(log_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["UTC_Timestamp", "CPU_Util_%", "Temp_C", "Fan_RPM", "Throttle_Hex"])
        
        print(f"Logging telemetry to {log_file}. Press Ctrl+C to stop.")
        
        try:
            while True:
                timestamp = datetime.now(timezone.utc).isoformat()
                cpu_util = psutil.cpu_percent(interval=None) # Set interval=None for non-blocking
                temp = get_temp()
                fan = get_fan_rpm()
                throttle = get_throttle_state()
                
                writer.writerow([timestamp, cpu_util, temp, fan, throttle])
                file.flush() # Ensure data writes to disk immediately
                
                time.sleep(0.5) # 2 Hz sampling rate
                
        except KeyboardInterrupt:
            print("\nLogging stopped.")

if __name__ == "__main__":
    main()