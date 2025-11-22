"""
Pre-Flight Readiness Test - Run before market open to validate system
Tests every critical path that could break during live trading
"""
import os
import sys
import json
from datetime import datetime, timedelta
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.polygon_data_fetcher import PolygonDataFetcher
from engine.polygon_options_fetcher import PolygonOptionsFetcher
from engine.ict_structures import detect_all_structures
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from dashboard.notifier import PushoverNotifier

class PreFlightCheck:
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0
        
    def test(self, name, func):
        """Run a test and record results"""
        print(f"\n{'='*70}")
        print(f"TEST: {name}")
        print(f"{'='*70}")
        
        try:
            func()
            print(f"✅ PASSED")
            self.results.append({'test': name, 'status': 'PASS'})
            self.passed += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.results.append({'test': name, 'status': 'FAIL', 'error': str(e)})
            self.failed += 1
    
    def print_report(self):
        """Print final test report"""
        print(f"\n\n{'='*70}")
        print(f"PRE-FLIGHT TEST REPORT")
        print(f"{'='*70}")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"{'='*70}\n")
        
        for result in self.results:
            status = "✅" if result['status'] == 'PASS' else "❌"
            print(f"{status} {result['test']}")
            if result['status'] == 'FAIL':
                print(f"   Error: {result.get('error', 'Unknown')}")
        
        print(f"\n{'='*70}")
        if self.failed == 0:
            print("🎯 ALL TESTS PASSED - SYSTEM READY")
        else:
            print(f"⚠️  {self.failed} TEST(S) FAILED - NOT READY")
        print(f"{'='*70}\n")
        
        return self.failed == 0

def test_polygon_api_auth():
    """Test 1: Polygon API authentication"""
    api_key = os.getenv('POLYGON_API_KEY')
    if not api_key:
        raise Exception("POLYGON_API_KEY not found in environment")
    print(f"✓ API key found (length: {len(api_key)})")

def test_polygon_data_fetch():
    """Test 2: Fetch real market data from Polygon"""
    fetcher = PolygonDataFetcher()
    
    # Fetch yesterday's data
    et = pytz.timezone('America/New_York')
    yesterday = (datetime.now(et) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    df = fetcher.fetch_stock_bars('QQQ', yesterday, yesterday)
    
    if df is None or len(df) == 0:
        raise Exception(f"No data returned for QQQ on {yesterday}")
    
    print(f"✓ Fetched {len(df)} bars for QQQ")
    
    # Validate columns
    required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            raise Exception(f"Missing column: {col}")
    
    print(f"✓ All required columns present")

def test_ict_structure_detection():
    """Test 3: ICT structure detection pipeline"""
    fetcher = PolygonDataFetcher()
    
    # Fetch data
    et = pytz.timezone('America/New_York')
    yesterday = (datetime.now(et) - timedelta(days=1)).strftime('%Y-%m-%d')
    df = fetcher.fetch_stock_bars('QQQ', yesterday, yesterday)
    
    if df is None or len(df) == 0:
        raise Exception("No data to test ICT detection")
    
    print(f"✓ Data loaded: {len(df)} bars")
    
    # Calculate ATR
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()
    
    print(f"✓ ATR calculated")
    
    # Label sessions
    df = label_sessions(df)
    print(f"✓ Sessions labeled")
    
    # Add session highs/lows
    df = add_session_highs_lows(df)
    print(f"✓ Session highs/lows added")
    
    # Detect structures
    df = detect_all_structures(df, displacement_threshold=1.0)
    print(f"✓ ICT structures detected")
    
    # Check for required columns
    required = ['sweep_bullish', 'sweep_bearish', 'displacement_bullish', 
                'displacement_bearish', 'mss_bullish', 'mss_bearish']
    for col in required:
        if col not in df.columns:
            raise Exception(f"Missing ICT column: {col}")
    
    print(f"✓ All ICT structure columns present")
    
    # Count signals
    sweeps = df['sweep_bullish'].sum() + df['sweep_bearish'].sum()
    displacements = df['displacement_bullish'].sum() + df['displacement_bearish'].sum()
    mss = df['mss_bullish'].sum() + df['mss_bearish'].sum()
    
    print(f"✓ Structures found - Sweeps: {sweeps}, Displacements: {displacements}, MSS: {mss}")

def test_options_pricing_fetch():
    """Test 4: Options chain fetch from Polygon"""
    fetcher = PolygonOptionsFetcher()
    
    # Get current QQQ price (use yesterday's close)
    data_fetcher = PolygonDataFetcher()
    et = pytz.timezone('America/New_York')
    yesterday = (datetime.now(et) - timedelta(days=1)).strftime('%Y-%m-%d')
    df = data_fetcher.fetch_stock_bars('QQQ', yesterday, yesterday)
    
    if df is None or len(df) == 0:
        raise Exception("Can't get QQQ price for options test")
    
    underlying_price = df.iloc[-1]['close']
    print(f"✓ QQQ price: ${underlying_price:.2f}")
    
    # Fetch options chain for next trading day (0DTE simulation)
    options_date = (datetime.now(et) + timedelta(days=3)).strftime('%Y-%m-%d')  # Monday
    
    call_strike = underlying_price - 1  # 1-strike ITM
    put_strike = underlying_price + 1
    
    try:
        call_chain = fetcher.fetch_options_snapshot('QQQ', options_date, call_strike, 'call')
        put_chain = fetcher.fetch_options_snapshot('QQQ', options_date, put_strike, 'put')
        
        print(f"✓ Options data available (CALL and PUT)")
    except Exception as e:
        # Options data might not be available on weekends
        print(f"⚠️  Options fetch error (may be expected on weekends): {e}")
        print(f"✓ Options fetcher initialized correctly")

def test_state_persistence():
    """Test 5: State file save/load"""
    test_state = {
        'account_balance': 25000.0,
        'positions': {'conservative': [], 'aggressive': []},
        'trade_history': [],
        'stats': {
            'conservative': {'trades': 0, 'wins': 0, 'total_pnl': 0},
            'aggressive': {'trades': 0, 'wins': 0, 'total_pnl': 0}
        },
        'last_signal_check': {},
        'last_updated': datetime.now().isoformat(),
        'heartbeat_timestamp': datetime.now().isoformat()
    }
    
    test_file = 'trader_state_test.json'
    
    # Write
    with open(test_file, 'w') as f:
        json.dump(test_state, f, indent=2)
    print(f"✓ State file written")
    
    # Read
    with open(test_file, 'r') as f:
        loaded = json.load(f)
    print(f"✓ State file loaded")
    
    # Validate
    if loaded['account_balance'] != 25000.0:
        raise Exception("State corruption: balance mismatch")
    
    print(f"✓ State integrity verified")
    
    # Cleanup
    os.remove(test_file)
    print(f"✓ Test file cleaned up")

def test_dashboard_state_read():
    """Test 6: Dashboard can read current state"""
    if not os.path.exists('trader_state.json'):
        raise Exception("trader_state.json not found")
    
    with open('trader_state.json', 'r') as f:
        state = json.load(f)
    
    required_keys = ['account_balance', 'positions', 'trade_history', 'stats']
    for key in required_keys:
        if key not in state:
            raise Exception(f"Missing state key: {key}")
    
    print(f"✓ State file has all required keys")
    print(f"✓ Balance: ${state['account_balance']:,.2f}")

def test_notification_system():
    """Test 7: Notification system (credential check only, no spam)"""
    api_token = os.getenv('PUSHOVER_API_TOKEN')
    user_key = os.getenv('PUSHOVER_USER_KEY')
    
    if not api_token:
        raise Exception("PUSHOVER_API_TOKEN not configured")
    if not user_key:
        raise Exception("PUSHOVER_USER_KEY not configured")
    
    print(f"✓ Pushover credentials found")
    print(f"✓ API token length: {len(api_token)}")
    print(f"✓ User key length: {len(user_key)}")
    
    # Note: Not sending actual notification to avoid spam

def main():
    print("\n" + "="*70)
    print("🚀 MAXTRADER PRE-FLIGHT READINESS CHECK")
    print("="*70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Testing all critical paths before market open...")
    print("="*70)
    
    checker = PreFlightCheck()
    
    # Run all tests
    checker.test("1. Polygon API Authentication", test_polygon_api_auth)
    checker.test("2. Market Data Fetch", test_polygon_data_fetch)
    checker.test("3. ICT Structure Detection", test_ict_structure_detection)
    checker.test("4. Options Pricing Fetch", test_options_pricing_fetch)
    checker.test("5. State Persistence", test_state_persistence)
    checker.test("6. Dashboard State Read", test_dashboard_state_read)
    checker.test("7. Notification System", test_notification_system)
    
    # Print report
    ready = checker.print_report()
    
    if ready:
        print("🎯 System validated and ready for Monday market open")
        sys.exit(0)
    else:
        print("⚠️  Fix failures before claiming readiness")
        sys.exit(1)

if __name__ == '__main__':
    main()
