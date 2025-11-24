"""
Production runner - keeps both dashboard and trader alive 24/7 for Autoscale deployment
"""
import subprocess
import time
import threading
import os
from datetime import datetime

def run_dashboard():
    """Run dashboard on port 5000 (required for Autoscale)"""
    print("🚀 Starting dashboard on port 5000...")
    # Set environment to ensure port 5000
    os.environ['PORT'] = '5000'
    subprocess.run(["python3", "dashboard/app.py"])

def run_trader():
    """Run auto-trader with auto-restart on crash"""
    while True:
        try:
            print("\n🤖 Starting auto-trader...")
            result = subprocess.run(["python3", "engine/auto_trader.py"])
            print(f"⚠️  Auto-trader exited with code {result.returncode}")
            print("🔄 Restarting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Error running trader: {e}")
            time.sleep(5)

def main():
    print("="*70)
    print("🚀 MAXTRADER PRODUCTION RUNNER (24/7)")
    print("="*70)
    print("Dashboard: http://0.0.0.0:5000")
    print("Auto-trader: Running in background")
    print("="*70 + "\n")
    
    # Start trader in background thread
    trader_thread = threading.Thread(target=run_trader, daemon=True)
    trader_thread.start()
    
    # Run dashboard in main thread (required for Autoscale HTTP)
    run_dashboard()

if __name__ == '__main__':
    main()
