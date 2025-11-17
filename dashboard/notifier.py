import os
import requests
from typing import Optional
from datetime import datetime


class PushoverNotifier:
    """
    Handles Pushover push notifications for critical trading events.
    """
    
    def __init__(self):
        self.user_key = os.getenv('PUSHOVER_USER_KEY')
        self.api_token = os.getenv('PUSHOVER_API_TOKEN')
        self.enabled = bool(self.user_key and self.api_token)
        self.api_url = "https://api.pushover.net/1/messages.json"
        
    def send_notification(
        self,
        message: str,
        title: str = "MaxTrader Alert",
        priority: int = 0,
        sound: Optional[str] = None
    ) -> bool:
        """
        Send a push notification via Pushover.
        
        Args:
            message: Notification message body
            title: Notification title
            priority: -2 (silent), -1 (quiet), 0 (normal), 1 (high), 2 (emergency)
            sound: Optional sound name (pushover, bike, bugle, etc.)
            
        Returns:
            True if notification sent successfully, False otherwise
        """
        if not self.enabled:
            print(f"[PUSHOVER DISABLED] {title}: {message}")
            return False
            
        try:
            payload = {
                "token": self.api_token,
                "user": self.user_key,
                "message": message,
                "title": title,
                "priority": priority,
            }
            
            if sound:
                payload["sound"] = sound
                
            response = requests.post(self.api_url, data=payload, timeout=10)
            
            if response.status_code == 200:
                print(f"[PUSHOVER SENT] {title}: {message}")
                return True
            else:
                # Silently disable on invalid credentials
                if response.status_code == 400:
                    self.enabled = False
                    print(f"[PUSHOVER DISABLED] Invalid credentials - notifications disabled")
                return False
                
        except Exception as e:
            print(f"[PUSHOVER EXCEPTION] {e}")
            return False
    
    def send_circuit_breaker_alert(self, breaker_name: str, reason: str):
        """Send high-priority alert for circuit breaker trigger."""
        message = f"🛑 Circuit Breaker Triggered: {breaker_name}\n\nReason: {reason}\n\nTrading has been auto-paused."
        self.send_notification(
            message=message,
            title="⚠️ CIRCUIT BREAKER",
            priority=1,
            sound="siren"
        )
    
    def send_loss_limit_alert(self, current_loss: float, limit: float):
        """Send high-priority alert for loss limit reached."""
        message = f"📉 Daily Loss Limit Reached\n\nCurrent Loss: ${current_loss:,.2f}\nLimit: ${limit:,.2f}\n\nTrading halted."
        self.send_notification(
            message=message,
            title="🚨 LOSS LIMIT",
            priority=1,
            sound="persistent"
        )
    
    def send_trade_executed(self, symbol: str, direction: str, structure: str, premium: float):
        """Send notification for trade execution."""
        message = f"{symbol} {direction}\nStructure: {structure}\nPremium: ${premium:,.2f}"
        self.send_notification(
            message=message,
            title=f"✅ Trade Executed",
            priority=0,
            sound="cashregister"
        )
    
    def send_trade_closed(self, symbol: str, pnl: float, reason: str):
        """Send notification for trade exit."""
        emoji = "💰" if pnl > 0 else "📉"
        message = f"{symbol} closed\nP&L: ${pnl:,.2f}\nReason: {reason}"
        self.send_notification(
            message=message,
            title=f"{emoji} Trade Closed",
            priority=0
        )
    
    def send_system_error(self, error_message: str):
        """Send high-priority alert for critical system errors."""
        self.send_notification(
            message=error_message,
            title="❌ SYSTEM ERROR",
            priority=1,
            sound="alien"
        )
    
    def send_daily_summary(self, trades: int, pnl: float, win_rate: float):
        """Send end-of-day summary."""
        emoji = "📈" if pnl >= 0 else "📉"
        message = f"Trades: {trades}\nP&L: ${pnl:,.2f}\nWin Rate: {win_rate:.1f}%"
        self.send_notification(
            message=message,
            title=f"{emoji} Daily Summary",
            priority=-1
        )


notifier = PushoverNotifier()
