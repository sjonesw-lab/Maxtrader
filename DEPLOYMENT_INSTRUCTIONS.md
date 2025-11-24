# MaxTrader Deployment Instructions

## Problem
- You only have Autoscale deployment (not Reserved VM)
- Autoscale scales down to zero after 15 min of no requests
- Auto-trader needs to run 24/7 to catch 9:25 AM market open

## Solution
Deploy with Autoscale using the production runner that:
1. Runs dashboard on port 5000 (keeps Autoscale alive with HTTP requests)
2. Runs auto-trader in background thread
3. Auto-restarts trader on crashes

## Steps to Deploy

1. **Click "Publishing" in left sidebar** (or search for "Publishing" tool)

2. **Select "Autoscale" deployment**

3. **Click "Set up your published app"**

4. **Configuration should already be set:**
   - Run command: `python3 run_production.py`
   - Port: 5000 (auto-detected)

5. **Click "Publish"**

6. **Once published:**
   - Dashboard will be live at your deployment URL
   - Auto-trader runs in background
   - System will auto-start trading at 9:25 AM ET every day
   - Will NOT scale down (dashboard keeps it alive)

## To Update After Code Changes

1. Go to Publishing tool
2. Click "Republish"
3. New code goes live

## Current Dev Workflow (Before Deployment)

The dev workflow will continue to miss market opens unless:
- You manually start it before 9:25 AM each day
- OR you deploy to production (recommended)

## Verification

After deployment:
1. Visit your deployment URL - should see dashboard
2. Check trader logs in deployment console
3. System will send Pushover notification at next 9:25 AM market open

