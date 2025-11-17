import os
import sys
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from datetime import datetime
import threading
import time
import json
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.notifier import notifier

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SESSION_SECRET', 'dev-secret-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*")


def load_trader_state():
    """Load current trader state from file."""
    try:
        import json
        state_file = '/tmp/trader_state.json'
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
    except:
        pass
    return None


class DashboardState:
    """Centralized state management for the dashboard."""
    
    def __init__(self):
        self.account_balance = 100000.00  # Alpaca paper account
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        
        # Dual strategy tracking
        self.conservative = {
            'risk_pct': 3.0,
            'allocation': '100% Longs',
            'trades': 0,
            'wins': 0,
            'total_pnl': 0.0,
            'active_positions': 0,
            'win_rate': 0.0
        }
        self.aggressive = {
            'risk_pct': 4.0,
            'allocation': '75% Longs / 25% Spreads',
            'trades': 0,
            'wins': 0,
            'total_pnl': 0.0,
            'active_positions': 0,
            'win_rate': 0.0
        }
        
        self.open_positions = []
        self.trade_history = []
        self.current_regime = "NORMAL_VOL"
        self.vix_level = 18.5
        self.market_open = False
        self.circuit_breakers = {
            "rapid_loss": {"triggered": False, "threshold": "2% in 15min"},
            "error_rate": {"triggered": False, "threshold": "3 errors in 5min"},
            "drawdown": {"triggered": False, "threshold": "5% from peak"}
        }
        self.safety_status = {
            "kill_switch": False,
            "daily_loss_limit": 1000.00,
            "current_loss": 0.0,
            "max_position_size": 500.00,
            "active_positions": 0,
            "max_positions": 3
        }
        self.system_health = {
            "status": "HEALTHY",
            "last_heartbeat": datetime.now().isoformat(),
            "uptime_seconds": 0,
            "error_count": 0
        }
        self.performance_metrics = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0
        }
        

state = DashboardState()


@app.route('/')
def index():
    """Render the main dashboard."""
    return render_template('dashboard.html')


@app.route('/api/state')
def get_state():
    """API endpoint to fetch current dashboard state."""
    return jsonify({
        'account_balance': state.account_balance,
        'daily_pnl': state.daily_pnl,
        'total_pnl': state.total_pnl,
        'market_open': state.market_open,
        'conservative': state.conservative,
        'aggressive': state.aggressive,
        'open_positions': state.open_positions,
        'trade_history': state.trade_history[-20:],
        'current_regime': state.current_regime,
        'vix_level': state.vix_level,
        'circuit_breakers': state.circuit_breakers,
        'safety_status': state.safety_status,
        'system_health': state.system_health,
        'performance_metrics': state.performance_metrics
    })


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    print(f"Client connected: {datetime.now()}")
    emit('initial_state', {
        'account_balance': state.account_balance,
        'daily_pnl': state.daily_pnl,
        'total_pnl': state.total_pnl,
        'current_regime': state.current_regime,
        'vix_level': state.vix_level,
        'safety_status': state.safety_status,
        'circuit_breakers': state.circuit_breakers,
        'performance_metrics': state.performance_metrics,
        'trade_history': state.trade_history[-20:],
        'open_positions': state.open_positions,
        'system_health': state.system_health
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    print(f"Client disconnected: {datetime.now()}")


@socketio.on('test_notification')
def handle_test_notification(data):
    """Test Pushover notification."""
    message = data.get('message', 'Test notification from MaxTrader Dashboard')
    success = notifier.send_notification(
        message=message,
        title="🧪 Test Notification",
        priority=0
    )
    emit('notification_result', {'success': success})


@socketio.on('kill_switch')
def handle_kill_switch():
    """Handle kill switch activation - PERMANENT until manual reset."""
    state.safety_status['kill_switch'] = True
    print(f"🛑 KILL SWITCH ACTIVATED at {datetime.now()}")
    
    with open('/tmp/maxtrader_kill_switch.lock', 'w') as f:
        f.write(f"ACTIVATED at {datetime.now().isoformat()}")
    
    notifier.send_notification(
        message="Kill switch activated! All trading has been halted immediately. Manual reset required.",
        title="🚨 KILL SWITCH ACTIVATED",
        priority=2,
        sound="siren"
    )
    
    broadcast_update('kill_switch_activated', {
        'timestamp': datetime.now().isoformat()
    })
    
    emit('kill_switch_result', {'success': True})


@socketio.on('reset_kill_switch')
def handle_reset_kill_switch(data):
    """Reset kill switch - requires confirmation code."""
    confirmation_code = data.get('code', '')
    
    if confirmation_code != 'RESET2025':
        emit('reset_result', {
            'success': False,
            'message': 'Invalid confirmation code'
        })
        return
    
    state.safety_status['kill_switch'] = False
    
    import os
    try:
        os.remove('/tmp/maxtrader_kill_switch.lock')
    except FileNotFoundError:
        pass
    
    print(f"✅ Kill switch RESET at {datetime.now()}")
    
    notifier.send_notification(
        message="Kill switch has been manually reset. Trading can resume.",
        title="✅ Kill Switch Reset",
        priority=1
    )
    
    broadcast_update('kill_switch_reset', {
        'timestamp': datetime.now().isoformat()
    })
    
    emit('reset_result', {
        'success': True,
        'message': 'Kill switch reset successfully'
    })


def broadcast_update(event_type: str, data: dict):
    """Broadcast real-time updates to all connected clients."""
    socketio.emit(event_type, data)


def simulate_market_updates():
    """
    Background thread to update dashboard from live trader state.
    """
    cycle_count = 0
    peak_balance = 100000.00
    last_loss_notification = 0
    last_circuit_check = time.time()
    
    while True:
        time.sleep(5)
        
        # Load live trader state
        trader_state = load_trader_state()
        if trader_state:
            stats = trader_state.get('stats', {})
            
            # Update conservative stats
            cons = stats.get('conservative', {})
            state.conservative['trades'] = cons.get('trades', 0)
            state.conservative['wins'] = cons.get('wins', 0)
            state.conservative['total_pnl'] = cons.get('total_pnl', 0.0)
            if state.conservative['trades'] > 0:
                state.conservative['win_rate'] = (state.conservative['wins'] / state.conservative['trades']) * 100
            
            # Update aggressive stats
            agg = stats.get('aggressive', {})
            state.aggressive['trades'] = agg.get('trades', 0)
            state.aggressive['wins'] = agg.get('wins', 0)
            state.aggressive['total_pnl'] = agg.get('total_pnl', 0.0)
            if state.aggressive['trades'] > 0:
                state.aggressive['win_rate'] = (state.aggressive['wins'] / state.aggressive['trades']) * 100
            
            # Update total P&L
            state.total_pnl = state.conservative['total_pnl'] + state.aggressive['total_pnl']
            
            # Count active positions
            positions = trader_state.get('positions', {})
            state.conservative['active_positions'] = len([p for p in positions.get('conservative', []) if p.get('status') == 'open'])
            state.aggressive['active_positions'] = len([p for p in positions.get('aggressive', []) if p.get('status') == 'open'])
        
        if state.safety_status['kill_switch']:
            print(f"⚠️  Kill switch active - trading halted")
            broadcast_update('system_health_update', {
                'status': 'KILL_SWITCH',
                'last_heartbeat': datetime.now().isoformat(),
                'uptime_seconds': state.system_health['uptime_seconds'],
                'error_count': 0
            })
            continue
        
        cycle_count += 1
        
        pnl_change = random.uniform(-50, 100)
        state.daily_pnl += pnl_change
        state.total_pnl += pnl_change
        state.account_balance = 50000 + state.total_pnl
        
        peak_balance = max(peak_balance, state.account_balance)
        
        state.vix_level = max(8, min(40, state.vix_level + random.uniform(-0.5, 0.5)))
        
        if state.vix_level < 13:
            state.current_regime = "ULTRA_LOW_VOL"
        elif state.vix_level < 30:
            state.current_regime = "NORMAL_VOL"
        else:
            state.current_regime = "HIGH_VOL"
        
        state.system_health['uptime_seconds'] += 5
        state.system_health['last_heartbeat'] = datetime.now().isoformat()
        
        for position in state.open_positions:
            position['current_pnl'] = random.uniform(-50, 150)
        
        if len(state.open_positions) > 0:
            broadcast_update('positions_update', {
                'positions': state.open_positions
            })
        
        if state.daily_pnl < 0:
            state.safety_status['current_loss'] = abs(state.daily_pnl)
        else:
            state.safety_status['current_loss'] = 0
        
        state.safety_status['active_positions'] = min(
            state.safety_status['max_positions'],
            len(state.open_positions)
        )
        
        loss_percent = (state.safety_status['current_loss'] / state.safety_status['daily_loss_limit']) * 100
        if loss_percent >= 100 and (time.time() - last_loss_notification) > 300:
            notifier.send_loss_limit_alert(
                current_loss=state.safety_status['current_loss'],
                limit=state.safety_status['daily_loss_limit']
            )
            last_loss_notification = time.time()
            state.safety_status['kill_switch'] = True
        
        if time.time() - last_circuit_check > 60:
            drawdown_pct = ((peak_balance - state.account_balance) / peak_balance) * 100
            if drawdown_pct >= 5:
                if not state.circuit_breakers['drawdown']['triggered']:
                    state.circuit_breakers['drawdown']['triggered'] = True
                    notifier.send_circuit_breaker_alert(
                        breaker_name="Drawdown Circuit Breaker",
                        reason=f"Drawdown reached {drawdown_pct:.1f}% from peak"
                    )
            last_circuit_check = time.time()
        
        if cycle_count % 15 == 0:
            if len(state.open_positions) < state.safety_status['max_positions'] and random.random() > 0.6:
                new_position = {
                    'id': f"POS-{len(state.open_positions) + 1}",
                    'symbol': 'QQQ',
                    'direction': random.choice(['CALL', 'PUT']),
                    'structure': random.choice(['Long Option', 'Debit Spread', 'Butterfly']),
                    'entry_price': random.uniform(100, 500),
                    'current_pnl': 0,
                    'entry_time': datetime.now().isoformat()
                }
                state.open_positions.append(new_position)
                broadcast_update('positions_update', {
                    'positions': state.open_positions
                })
            
            elif len(state.open_positions) > 0 and random.random() > 0.5:
                closed_position = state.open_positions.pop(0)
                trade_pnl = random.uniform(-200, 500)
                
                state.performance_metrics['total_trades'] += 1
                
                if trade_pnl > 0:
                    state.performance_metrics['winning_trades'] += 1
                else:
                    state.performance_metrics['losing_trades'] += 1
                
                if state.performance_metrics['total_trades'] > 0:
                    state.performance_metrics['win_rate'] = (
                        state.performance_metrics['winning_trades'] / 
                        state.performance_metrics['total_trades']
                    ) * 100
                
                trade = {
                    'timestamp': datetime.now().isoformat(),
                    'symbol': closed_position['symbol'],
                    'direction': closed_position['direction'],
                    'structure': closed_position['structure'],
                    'pnl': trade_pnl,
                    'regime': state.current_regime
                }
                state.trade_history.append(trade)
                
                broadcast_update('positions_update', {
                    'positions': state.open_positions
                })
                
                if abs(trade_pnl) > 300:
                    notifier.send_trade_closed(
                        closed_position['symbol'],
                        trade_pnl,
                        'Target reached' if trade_pnl > 0 else 'Stop loss hit'
                    )
        
        broadcast_update('pnl_update', {
            'daily_pnl': state.daily_pnl,
            'total_pnl': state.total_pnl,
            'account_balance': state.account_balance
        })
        
        broadcast_update('regime_update', {
            'current_regime': state.current_regime,
            'vix_level': state.vix_level
        })
        
        broadcast_update('safety_update', state.safety_status)
        
        broadcast_update('breaker_update', state.circuit_breakers)
        
        broadcast_update('performance_update', state.performance_metrics)
        
        broadcast_update('system_health_update', state.system_health)
        
        if len(state.trade_history) > 0:
            broadcast_update('trade_history_update', {
                'trades': state.trade_history[-20:]
            })


if __name__ == '__main__':
    import os
    if os.path.exists('/tmp/maxtrader_kill_switch.lock'):
        state.safety_status['kill_switch'] = True
        print("\n⚠️  KILL SWITCH LOCK FILE DETECTED")
        print("⚠️  Trading will remain HALTED until manual reset")
        print("⚠️  Use reset code: RESET2025\n")
    
    threading.Thread(target=simulate_market_updates, daemon=True).start()
    
    print("\n" + "="*60)
    print("🚀 MaxTrader Professional Dashboard Starting...")
    print("="*60)
    print(f"📊 Dashboard URL: http://0.0.0.0:5000")
    print(f"🔔 Pushover Notifications: {'ENABLED' if notifier.enabled else 'DISABLED'}")
    print(f"🛑 Kill Switch: {'ACTIVE (TRADING HALTED)' if state.safety_status['kill_switch'] else 'Ready'}")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
