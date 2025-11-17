const socket = io();

let pnlChartInstance = null;
const pnlData = {
    labels: [],
    values: []
};

function formatCurrency(value) {
    const sign = value >= 0 ? '+' : '';
    return sign + '$' + value.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function formatPercent(value) {
    return value.toFixed(1) + '%';
}

function updateTimestamp() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('en-US', { hour12: false });
    document.getElementById('timestamp').textContent = timeString;
}

function updateRegime(regime, vix) {
    const regimeEl = document.getElementById('regimeValue');
    const vixEl = document.getElementById('vixValue');
    
    regimeEl.textContent = regime;
    vixEl.textContent = `VIX: ${vix.toFixed(1)}`;
    
    let color;
    if (regime === 'ULTRA_LOW_VOL') {
        color = 'var(--accent-info)';
    } else if (regime === 'NORMAL_VOL') {
        color = 'var(--accent-primary)';
    } else if (regime === 'HIGH_VOL') {
        color = 'var(--accent-warning)';
    } else {
        color = 'var(--accent-danger)';
    }
    
    regimeEl.style.color = color;
}

function updatePnl(dailyPnl, totalPnl, accountBalance) {
    const dailyEl = document.getElementById('dailyPnl');
    const totalEl = document.getElementById('totalPnl');
    const balanceEl = document.getElementById('accountBalance');
    
    dailyEl.textContent = formatCurrency(dailyPnl);
    totalEl.textContent = formatCurrency(totalPnl);
    balanceEl.textContent = formatCurrency(accountBalance);
    
    dailyEl.className = 'metric-value pnl ' + (dailyPnl >= 0 ? 'positive' : 'negative');
    totalEl.className = 'metric-value pnl ' + (totalPnl >= 0 ? 'positive' : 'negative');
    
    addPnlDataPoint(dailyPnl);
}

function updateSafetyStatus(safety) {
    const lossPercent = Math.min(100, (Math.abs(safety.current_loss) / safety.daily_loss_limit) * 100);
    const positionPercent = (safety.active_positions / safety.max_positions) * 100;
    
    const lossBar = document.getElementById('lossLimitBar');
    const positionBar = document.getElementById('positionBar');
    const lossText = document.getElementById('lossLimitText');
    const positionText = document.getElementById('positionText');
    
    lossBar.style.width = lossPercent + '%';
    lossBar.className = 'safety-bar-fill';
    if (lossPercent > 80) {
        lossBar.classList.add('danger');
    } else if (lossPercent > 50) {
        lossBar.classList.add('warning');
    }
    
    positionBar.style.width = positionPercent + '%';
    
    lossText.textContent = `${formatCurrency(Math.abs(safety.current_loss))} / ${formatCurrency(safety.daily_loss_limit)}`;
    positionText.textContent = `${safety.active_positions} / ${safety.max_positions} positions`;
}

function updateCircuitBreakers(breakers) {
    updateBreaker('rapidLossBreaker', breakers.rapid_loss);
    updateBreaker('errorRateBreaker', breakers.error_rate);
    updateBreaker('drawdownBreaker', breakers.drawdown);
}

function updateBreaker(elementId, breaker) {
    const el = document.getElementById(elementId);
    const statusEl = el.querySelector('.breaker-status');
    
    if (breaker.triggered) {
        el.classList.add('triggered');
        statusEl.textContent = 'TRIGGERED';
        statusEl.classList.add('triggered');
    } else {
        el.classList.remove('triggered');
        statusEl.textContent = 'OK';
        statusEl.classList.remove('triggered');
    }
}

function updatePerformance(metrics) {
    document.getElementById('totalTrades').textContent = metrics.total_trades || 0;
    document.getElementById('winRate').textContent = formatPercent(metrics.win_rate || 0);
    document.getElementById('profitFactor').textContent = (metrics.profit_factor || 0).toFixed(2);
    document.getElementById('sharpeRatio').textContent = (metrics.sharpe_ratio || 0).toFixed(2);
}

function initPnlChart() {
    const ctx = document.getElementById('pnlChart').getContext('2d');
    
    pnlChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: pnlData.labels,
            datasets: [{
                label: 'Daily P&L',
                data: pnlData.values,
                borderColor: 'rgb(59, 130, 246)',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    grid: {
                        color: 'rgba(45, 53, 72, 0.5)'
                    },
                    ticks: {
                        color: '#9ca3af',
                        callback: function(value) {
                            return '$' + value.toFixed(0);
                        }
                    }
                },
                x: {
                    grid: {
                        color: 'rgba(45, 53, 72, 0.5)'
                    },
                    ticks: {
                        color: '#9ca3af'
                    }
                }
            }
        }
    });
}

function addPnlDataPoint(value) {
    const now = new Date();
    const timeLabel = now.toLocaleTimeString('en-US', { 
        hour12: false,
        hour: '2-digit',
        minute: '2-digit'
    });
    
    pnlData.labels.push(timeLabel);
    pnlData.values.push(value);
    
    if (pnlData.labels.length > 50) {
        pnlData.labels.shift();
        pnlData.values.shift();
    }
    
    if (pnlChartInstance) {
        pnlChartInstance.update('none');
    }
}

socket.on('connect', () => {
    console.log('Connected to server');
    document.getElementById('connectionStatus').textContent = 'Connected';
    document.getElementById('connectionStatus').classList.remove('disconnected');
});

socket.on('disconnect', () => {
    console.log('Disconnected from server');
    document.getElementById('connectionStatus').textContent = 'Disconnected';
    document.getElementById('connectionStatus').classList.add('disconnected');
});

socket.on('initial_state', (data) => {
    console.log('Initial state received:', data);
    updateRegime(data.current_regime, data.vix_level);
    updatePnl(data.daily_pnl, data.total_pnl, data.account_balance);
    
    if (data.safety_status) {
        updateSafetyStatus(data.safety_status);
    }
    
    if (data.circuit_breakers) {
        updateCircuitBreakers(data.circuit_breakers);
    }
    
    if (data.performance_metrics) {
        updatePerformance(data.performance_metrics);
    }
    
    if (data.trade_history && data.trade_history.length > 0) {
        updateTradeHistory(data.trade_history);
    }
    
    if (data.system_health) {
        updateSystemHealth(data.system_health);
    }
});

socket.on('pnl_update', (data) => {
    updatePnl(data.daily_pnl, data.total_pnl, data.account_balance);
});

socket.on('regime_update', (data) => {
    updateRegime(data.current_regime, data.vix_level);
});

socket.on('safety_update', (data) => {
    updateSafetyStatus(data);
});

socket.on('breaker_update', (data) => {
    updateCircuitBreakers(data);
});

socket.on('performance_update', (data) => {
    updatePerformance(data);
});

socket.on('trade_history_update', (data) => {
    updateTradeHistory(data.trades);
});

socket.on('positions_update', (data) => {
    updateOpenPositions(data.positions);
});

socket.on('system_health_update', (data) => {
    updateSystemHealth(data);
});

socket.on('kill_switch_activated', (data) => {
    document.getElementById('systemStatus').innerHTML = 
        '<div class="status-dot status-error"></div><span>KILL SWITCH</span>';
    const statusEl = document.getElementById('notificationStatus');
    statusEl.textContent = '🛑 KILL SWITCH ACTIVATED - All trading halted';
    statusEl.className = 'notification-status error';
    statusEl.style.display = 'block';
});

socket.on('notification_result', (data) => {
    const statusEl = document.getElementById('notificationStatus');
    if (data.success) {
        statusEl.textContent = '✅ Test notification sent successfully! Check your device.';
        statusEl.className = 'notification-status success';
    } else {
        statusEl.textContent = '❌ Failed to send notification. Check your Pushover credentials.';
        statusEl.className = 'notification-status error';
    }
    
    setTimeout(() => {
        statusEl.style.display = 'none';
    }, 5000);
});

socket.on('kill_switch_result', (data) => {
    if (data.success) {
        alert('🛑 KILL SWITCH ACTIVATED\n\nAll trading has been halted immediately.\nPushover notification sent.');
    }
});

function updateTradeHistory(trades) {
    const historyEl = document.getElementById('tradeHistory');
    
    if (!trades || trades.length === 0) {
        historyEl.innerHTML = '<div class="empty-state">No trades yet</div>';
        return;
    }
    
    historyEl.innerHTML = trades.slice().reverse().map(trade => {
        const time = new Date(trade.timestamp).toLocaleTimeString('en-US', { 
            hour12: false,
            hour: '2-digit',
            minute: '2-digit'
        });
        const pnlClass = trade.pnl >= 0 ? 'positive' : 'negative';
        const pnlSign = trade.pnl >= 0 ? '+' : '';
        
        return `
            <div class="trade-item">
                <div>
                    <strong>${trade.symbol}</strong> ${trade.direction} | ${trade.structure}
                    <br>
                    <small style="color: var(--text-muted);">${time} | ${trade.regime}</small>
                </div>
                <div class="${pnlClass}" style="font-weight: 700;">
                    ${pnlSign}$${trade.pnl.toFixed(2)}
                </div>
            </div>
        `;
    }).join('');
}

function updateOpenPositions(positions) {
    const positionsEl = document.getElementById('positionsTable');
    
    if (!positions || positions.length === 0) {
        positionsEl.innerHTML = '<div class="empty-state">No open positions</div>';
        return;
    }
    
    positionsEl.innerHTML = `
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="text-align: left; border-bottom: 1px solid var(--border-color);">
                    <th style="padding: 0.5rem;">Symbol</th>
                    <th style="padding: 0.5rem;">Type</th>
                    <th style="padding: 0.5rem;">Structure</th>
                    <th style="padding: 0.5rem;">Entry</th>
                    <th style="padding: 0.5rem;">P&L</th>
                </tr>
            </thead>
            <tbody>
                ${positions.map(pos => `
                    <tr style="border-bottom: 1px solid rgba(45, 53, 72, 0.5);">
                        <td style="padding: 0.75rem;"><strong>${pos.symbol}</strong></td>
                        <td style="padding: 0.75rem;">${pos.direction}</td>
                        <td style="padding: 0.75rem;">${pos.structure}</td>
                        <td style="padding: 0.75rem;">$${pos.entry_price.toFixed(2)}</td>
                        <td style="padding: 0.75rem; color: ${pos.current_pnl >= 0 ? 'var(--accent-success)' : 'var(--accent-danger)'};">
                            ${pos.current_pnl >= 0 ? '+' : ''}$${pos.current_pnl.toFixed(2)}
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

function updateSystemHealth(health) {
    const statusEl = document.getElementById('systemStatus');
    
    if (!health) return;
    
    let statusClass = 'status-healthy';
    let statusText = 'HEALTHY';
    
    if (health.status === 'WARNING') {
        statusClass = 'status-warning';
        statusText = 'WARNING';
    } else if (health.status === 'ERROR' || health.error_count > 0) {
        statusClass = 'status-error';
        statusText = 'ERROR';
    }
    
    statusEl.innerHTML = `<div class="status-dot ${statusClass}"></div><span>${statusText}</span>`;
}

document.getElementById('testNotificationBtn').addEventListener('click', () => {
    socket.emit('test_notification', {
        message: 'This is a test notification from MaxTrader Dashboard!'
    });
});

document.getElementById('killSwitchBtn').addEventListener('click', () => {
    if (confirm('⚠️ EMERGENCY KILL SWITCH ⚠️\n\nAre you ABSOLUTELY SURE you want to activate the kill switch?\n\nThis will:\n• Immediately halt ALL trading\n• Close monitoring systems\n• Send high-priority Pushover alert\n\nClick OK to confirm, Cancel to abort.')) {
        console.log('Kill switch activated by user');
        socket.emit('kill_switch');
    }
});

setInterval(updateTimestamp, 1000);
updateTimestamp();

fetch('/api/state')
    .then(response => response.json())
    .then(data => {
        updateRegime(data.current_regime, data.vix_level);
        updatePnl(data.daily_pnl, data.total_pnl, data.account_balance);
        updateSafetyStatus(data.safety_status);
        updateCircuitBreakers(data.circuit_breakers);
        updatePerformance(data.performance_metrics);
    })
    .catch(error => console.error('Error fetching initial state:', error));

window.addEventListener('load', () => {
    initPnlChart();
});
