# Deployment Fix - Port 5000 Issue

## Problem
Deployment is trying to run `python3 engine/auto_trader.py` instead of `python3 run_production.py`

## The .replit file is CORRECT
Line 62 shows: `run = ["python3", "run_production.py"]`

## Fix Steps

### Option 1: Force Refresh in Deployment UI
1. Open **Publishing** tool (left sidebar)
2. If you see an existing deployment, **delete it** first
3. Click "Set up your published app" 
4. In the deployment setup screen:
   - **Manually enter run command**: `python3 run_production.py`
   - **Verify port**: Should auto-detect 5000
5. Click "Publish"

### Option 2: Manual Override
If the UI doesn't let you edit the command:
1. Go to Publishing tool
2. Look for "Advanced settings" or "Configuration"
3. Find "Run command" field
4. **Change it to**: `python3 run_production.py`
5. Save and republish

### Option 3: Clear Cache
1. Close Replit tab completely
2. Reopen project
3. Go to Publishing → Delete existing deployment
4. Set up fresh deployment with correct command

## What the Production Runner Does
- Opens port 5000 immediately (required for Autoscale)
- Runs dashboard web server (keeps Autoscale alive)
- Runs auto-trader in background thread
- Auto-restarts trader on crashes

## Verification
After successful deployment, you should see in logs:
```
🚀 MAXTRADER PRODUCTION RUNNER (24/7)
Dashboard: http://0.0.0.0:5000
🚀 Starting dashboard on port 5000...
🤖 Starting auto-trader...
```

The deployment should stay up and not show "failed to open port 5000" error.
