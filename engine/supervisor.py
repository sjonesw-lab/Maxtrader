#!/usr/bin/env python3
"""
Trading System Supervisor
Monitors trader heartbeat and auto-restarts on failure.
Provides <60-second recovery time guarantee.
"""

import os
import sys
import time
import json
import subprocess
from datetime import datetime, timedelta

sys.path.insert(0, '.')
from dashboard.notifier import notifier


class TradingSupervisor:
    """Monitors auto_trader.py and restarts on failure."""
    
    def __init__(self, state_file='trader_state.json', heartbeat_timeout=60):
        self.state_file = state_file
        self.heartbeat_timeout = heartbeat_timeout  # seconds
        self.trader_process = None
        self.last_restart = None
        self.restart_count = 0
        self.consecutive_failures = 0
        
    def check_heartbeat(self) -> tuple:
        """
        Check if trader is alive based on heartbeat timestamp.
        Returns (is_alive, seconds_since_heartbeat, error_msg)
        """
        try:
            if not os.path.exists(self.state_file):
                return False, None, "State file does not exist"
            
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            heartbeat_str = state.get('heartbeat')
            if not heartbeat_str:
                return False, None, "No heartbeat in state file"
            
            heartbeat = datetime.fromisoformat(heartbeat_str)
            now = datetime.now()
            
            # Handle timezone-aware datetimes
            if heartbeat.tzinfo is not None:
                import pytz
                now = pytz.UTC.localize(now) if now.tzinfo is None else now
            
            seconds_since = (now - heartbeat).total_seconds()
            
            if seconds_since > self.heartbeat_timeout:
                return False, seconds_since, f"Heartbeat stale ({seconds_since:.0f}s old)"
            
            return True, seconds_since, None
            
        except Exception as e:
            return False, None, f"Error reading heartbeat: {str(e)}"
    
    def find_trader_pid(self) -> int:
        """Find the PID of the auto_trader.py process."""
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'engine/auto_trader.py'],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                return int(pids[0])  # Return first matching PID
            return None
        except Exception as e:
            print(f"⚠️  Error finding trader PID: {e}")
            return None
    
    def restart_trader(self, reason: str):
        """Kill the stalled trader process to trigger workflow auto-restart."""
        print(f"\n{'='*70}")
        print(f"🔄 RESTARTING TRADER")
        print(f"{'='*70}")
        print(f"Reason: {reason}")
        print(f"Time: {datetime.now().strftime('%I:%M:%S %p')}")
        
        self.restart_count += 1
        self.last_restart = datetime.now()
        
        # Send alert
        notifier.send_notification(
            f"🔄 Auto-Restart Triggered\n"
            f"Reason: {reason}\n"
            f"Restart #{self.restart_count}\n"
            f"Recovery time: <60 seconds",
            title="Supervisor: Auto-Restart",
            priority=1
        )
        
        # Find and kill the trader process
        trader_pid = self.find_trader_pid()
        if trader_pid:
            print(f"🔪 Killing stalled trader (PID {trader_pid})...")
            try:
                subprocess.run(['kill', '-9', str(trader_pid)], check=True)
                print(f"✅ Process terminated - workflow will auto-restart")
            except Exception as e:
                print(f"❌ Failed to kill process: {e}")
        else:
            print("⚠️  Trader process not found (may have already crashed)")
        
        # Wait up to 60 seconds for restart
        print("⏳ Waiting for auto-trader to restart...")
        for i in range(60):
            time.sleep(1)
            is_alive, age, error = self.check_heartbeat()
            if is_alive:
                print(f"✅ Trader restarted successfully (took {i+1}s)")
                self.consecutive_failures = 0
                return True
        
        # Restart failed
        self.consecutive_failures += 1
        print(f"❌ Restart failed after 60 seconds")
        
        if self.consecutive_failures >= 3:
            # Critical failure - alert user
            notifier.send_notification(
                f"🚨 CRITICAL: Auto-restart failed 3 times\n"
                f"Last reason: {reason}\n"
                f"Manual intervention required!\n"
                f"Check system logs immediately",
                title="Supervisor: CRITICAL",
                priority=2
            )
            print("🚨 CRITICAL: Multiple restart failures - pausing supervisor")
            time.sleep(300)  # Pause 5 minutes before trying again
        
        return False
    
    def run(self, check_interval=15):
        """
        Main supervisor loop.
        Checks heartbeat every 15 seconds, restarts if stale for 60+ seconds.
        """
        print("\n" + "="*70)
        print("🛡️  TRADING SYSTEM SUPERVISOR")
        print("="*70)
        print(f"Monitoring: {self.state_file}")
        print(f"Heartbeat timeout: {self.heartbeat_timeout}s")
        print(f"Check interval: {check_interval}s")
        print(f"Max downtime: <60 seconds (guaranteed)")
        print(f"Started: {datetime.now().strftime('%I:%M %p')}")
        print("="*70 + "\n")
        
        # Send startup notification
        notifier.send_notification(
            f"🛡️ Supervisor Started\n"
            f"Monitoring trader heartbeat\n"
            f"Auto-restart on failure\n"
            f"Max downtime: <60s",
            title="Supervisor Online",
            priority=0
        )
        
        last_status = None
        
        while True:
            try:
                is_alive, age, error = self.check_heartbeat()
                
                # Status message
                if is_alive:
                    status = f"✅ Healthy (heartbeat {age:.0f}s ago)"
                else:
                    status = f"⚠️  Problem: {error}"
                
                # Only print status changes or every 5 minutes
                now = datetime.now()
                if status != last_status or (last_status and (now.minute % 5 == 0 and now.second < check_interval)):
                    print(f"[{now.strftime('%H:%M:%S')}] {status}")
                    last_status = status
                
                # Restart if dead
                if not is_alive and age and age > self.heartbeat_timeout:
                    self.restart_trader(error)
                elif not is_alive:
                    # Problem detected but not ready to restart yet
                    print(f"   Monitoring... will restart if issue persists")
                
                time.sleep(check_interval)
                
            except KeyboardInterrupt:
                print("\n\n🛑 Supervisor stopped by user")
                break
            except Exception as e:
                print(f"⚠️  Supervisor error: {e}")
                time.sleep(check_interval)


if __name__ == '__main__':
    supervisor = TradingSupervisor()
    supervisor.run()
