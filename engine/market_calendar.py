#!/usr/bin/env python3
"""
US Stock Market Calendar
Handles market holidays and early close days for NYSE/NASDAQ
"""

from datetime import datetime, date, timedelta
from typing import Tuple, Optional
import pytz


class MarketCalendar:
    """Knows all market holidays and early close days."""
    
    # Market closed (full day holidays)
    HOLIDAYS_2024 = [
        date(2024, 1, 1),   # New Year's Day
        date(2024, 1, 15),  # MLK Day
        date(2024, 2, 19),  # Presidents' Day
        date(2024, 3, 29),  # Good Friday
        date(2024, 5, 27),  # Memorial Day
        date(2024, 6, 19),  # Juneteenth
        date(2024, 7, 4),   # Independence Day
        date(2024, 9, 2),   # Labor Day
        date(2024, 11, 28), # Thanksgiving
        date(2024, 12, 25), # Christmas
    ]
    
    HOLIDAYS_2025 = [
        date(2025, 1, 1),   # New Year's Day
        date(2025, 1, 9),   # National Day of Mourning (President Carter)
        date(2025, 1, 20),  # MLK Day
        date(2025, 2, 17),  # Presidents' Day
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 26),  # Memorial Day
        date(2025, 6, 19),  # Juneteenth
        date(2025, 7, 4),   # Independence Day
        date(2025, 9, 1),   # Labor Day
        date(2025, 11, 27), # Thanksgiving
        date(2025, 12, 25), # Christmas
    ]
    
    HOLIDAYS_2026 = [
        date(2026, 1, 1),   # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents' Day
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),   # Independence Day (observed)
        date(2026, 9, 7),   # Labor Day
        date(2026, 11, 26), # Thanksgiving
        date(2026, 12, 25), # Christmas
    ]
    
    # Early close days (1:00 PM ET)
    EARLY_CLOSE_2024 = [
        date(2024, 7, 3),   # Day before July 4th
        date(2024, 11, 29), # Black Friday
        date(2024, 12, 24), # Christmas Eve
    ]
    
    EARLY_CLOSE_2025 = [
        date(2025, 7, 3),   # Day before July 4th
        date(2025, 11, 28), # Black Friday
        date(2025, 12, 24), # Christmas Eve
    ]
    
    EARLY_CLOSE_2026 = [
        date(2026, 7, 2),   # Day before July 4th
        date(2026, 11, 27), # Black Friday
        date(2026, 12, 24), # Christmas Eve
    ]
    
    def __init__(self):
        self.et_tz = pytz.timezone('America/New_York')
        self.all_holidays = (
            self.HOLIDAYS_2024 + self.HOLIDAYS_2025 + self.HOLIDAYS_2026
        )
        self.all_early_close = (
            self.EARLY_CLOSE_2024 + self.EARLY_CLOSE_2025 + self.EARLY_CLOSE_2026
        )
    
    def get_current_et_time(self) -> datetime:
        """Get current time in Eastern Time."""
        return datetime.now(self.et_tz)
    
    def is_trading_day(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if given date is a trading day (not weekend, not holiday).
        
        Args:
            dt: datetime to check (defaults to now)
        
        Returns:
            True if market is open this day
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        # Convert to date for comparison
        check_date = dt.date()
        
        # Weekend?
        if check_date.weekday() >= 5:
            return False
        
        # Holiday?
        if check_date in self.all_holidays:
            return False
        
        return True
    
    def is_early_close_day(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if given date is an early close day (1:00 PM ET).
        
        Args:
            dt: datetime to check (defaults to now)
        
        Returns:
            True if market closes at 1:00 PM ET
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        check_date = dt.date()
        return check_date in self.all_early_close
    
    def get_market_hours(self, dt: Optional[datetime] = None) -> Tuple[datetime, datetime]:
        """
        Get market open/close times for given date.
        
        Args:
            dt: datetime to check (defaults to now)
        
        Returns:
            Tuple of (open_time, close_time) in ET
        """
        if dt is None:
            dt = self.get_current_et_time()
        
        # Regular hours: 9:30 AM - 4:00 PM ET
        open_time = dt.replace(hour=9, minute=30, second=0, microsecond=0)
        
        # Early close: 1:00 PM ET
        if self.is_early_close_day(dt):
            close_time = dt.replace(hour=13, minute=0, second=0, microsecond=0)
        else:
            close_time = dt.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return open_time, close_time
    
    def is_market_open_now(self) -> bool:
        """
        Check if market is open RIGHT NOW.
        
        Returns:
            True if market is currently open for trading
        """
        now = self.get_current_et_time()
        
        # Trading day?
        if not self.is_trading_day(now):
            return False
        
        # Within market hours?
        open_time, close_time = self.get_market_hours(now)
        
        if now < open_time or now >= close_time:
            return False
        
        return True
    
    def should_start_trading(self) -> bool:
        """
        Check if we should START trading (9:25 AM ET on trading days).
        
        Returns:
            True if it's time to start the trading session
        """
        now = self.get_current_et_time()
        
        # Trading day?
        if not self.is_trading_day(now):
            return False
        
        # Between 9:25 AM and 9:30 AM?
        if now.hour == 9 and 25 <= now.minute < 30:
            return True
        
        # Already past 9:30? Start immediately
        open_time, _ = self.get_market_hours(now)
        if now >= open_time:
            return True
        
        return False
    
    def should_stop_trading(self) -> bool:
        """
        Check if we should STOP trading.
        
        Regular days: 4:05 PM ET
        Early close days: 1:05 PM ET
        
        Returns:
            True if it's time to stop the trading session
        """
        now = self.get_current_et_time()
        
        # Not a trading day? Stop immediately
        if not self.is_trading_day(now):
            return True
        
        _, close_time = self.get_market_hours(now)
        
        # Add 5 minute buffer after market close
        stop_time = close_time.replace(minute=close_time.minute + 5)
        
        if now >= stop_time:
            return True
        
        return False
    
    def time_until_next_session(self) -> str:
        """
        Get human-readable time until next trading session.
        
        Returns:
            String like "Market opens Monday at 9:30 AM ET"
        """
        now = self.get_current_et_time()
        
        # If it's a trading day and before open
        if self.is_trading_day(now):
            open_time, _ = self.get_market_hours(now)
            if now < open_time:
                minutes_until = int((open_time - now).total_seconds() / 60)
                return f"Market opens in {minutes_until} minutes at 9:30 AM ET"
        
        # Find next trading day
        check_date = now + timedelta(days=1)
        days_checked = 0
        
        while days_checked < 10:
            if self.is_trading_day(check_date):
                day_name = check_date.strftime('%A')
                return f"Market opens {day_name} at 9:30 AM ET"
            check_date += timedelta(days=1)
            days_checked += 1
        
        return "Market closed"
    
    def get_status_message(self) -> str:
        """
        Get current market status message.
        
        Returns:
            Human-readable status string
        """
        now = self.get_current_et_time()
        
        if not self.is_trading_day(now):
            return f"🔴 Market Closed - {self.time_until_next_session()}"
        
        open_time, close_time = self.get_market_hours(now)
        
        if now < open_time:
            minutes_until = int((open_time - now).total_seconds() / 60)
            return f"🟡 Pre-Market - Opens in {minutes_until} min at 9:30 AM ET"
        
        if now >= close_time:
            return f"🔴 Market Closed - {self.time_until_next_session()}"
        
        # Market open
        early_close = " (Early Close 1:00 PM)" if self.is_early_close_day(now) else ""
        return f"🟢 Market Open{early_close}"


if __name__ == '__main__':
    # Quick test
    cal = MarketCalendar()
    print(f"Current ET Time: {cal.get_current_et_time()}")
    print(f"Is Trading Day: {cal.is_trading_day()}")
    print(f"Is Market Open: {cal.is_market_open_now()}")
    print(f"Should Start Trading: {cal.should_start_trading()}")
    print(f"Should Stop Trading: {cal.should_stop_trading()}")
    print(f"Status: {cal.get_status_message()}")
