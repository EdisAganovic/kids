import time
import requests
import os
import sys
from datetime import datetime

# Configuration
API_URL = "http://127.0.0.1:8000/api/session/status"
CHECK_INTERVAL = 10  # seconds

def log_message(message):
    """Log message with timestamp"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def lock_workstation():
    """Lock the Windows workstation"""
    try:
        log_message("Locking workstation...")
        os.system("rundll32.exe user32.dll,LockWorkStation")
    except Exception as e:
        log_message(f"Error locking workstation: {e}")

def main():
    log_message("PC Locker started")
    
    while True:
        try:
            # Get session status from the API
            response = requests.get(API_URL, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("is_active") and data.get("time_remaining_seconds", 0) <= 0:
                    log_message("Time exhausted, locking workstation...")
                    lock_workstation()
                    
            elif response.status_code == 404:
                log_message("No active session or server not responding")
            
        except requests.exceptions.RequestException as e:
            log_message(f"Error connecting to server: {e}")
        except Exception as e:
            log_message(f"Unexpected error: {e}")
        
        # Wait before next check
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()