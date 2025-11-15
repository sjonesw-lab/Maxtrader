"""
Options engine for building and simulating options structures.

Supports:
- Long options (calls/puts)
- Debit spreads
- Butterflies
- Broken-wing butterflies
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import pandas as pd
import numpy as np


def calculate_0dte_expiry(entry_time: pd.Timestamp) -> pd.Timestamp:
    """
    Calculate 0DTE (same-day) expiry time for QQQ options.
    
    QQQ options expire at 4:15 PM ET on the same trading day.
    
    Args:
        entry_time: Entry timestamp (can be tz-aware or naive)
        
    Returns:
        Expiry timestamp (4:15 PM same day) with same timezone as entry_time
    """
    # Preserve timezone from entry_time
    if entry_time.tz is not None:
        tz = entry_time.tz
    else:
        tz = None  # Keep naive if input is naive
    
    entry_date = entry_time.date()
    
    # Create expiry at 4:15 PM same day with matching timezone
    expiry = pd.Timestamp(
        year=entry_date.year,
        month=entry_date.month,
        day=entry_date.day,
        hour=16,
        minute=15,
        tz=tz
    )
    
    return expiry


@dataclass
class Option:
    """Single option leg."""
    kind: str
    strike: float
    expiry: pd.Timestamp
    is_long: bool
    quantity: int
    premium: float


@dataclass
class OptionPosition:
    """Complete options position with multiple legs."""
    options: List[Option]
    direction: str
    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp] = None
    entry_cost: float = 0.0
    target: Optional[float] = None
    
    def __post_init__(self):
        if self.entry_cost == 0.0:
            CONTRACT_MULTIPLIER = 100  # Options contracts represent 100 shares
            
            # Calculate theoretical premium cost (convert per-share to per-contract)
            theoretical_cost = sum(
                opt.premium * opt.quantity * CONTRACT_MULTIPLIER * (1 if opt.is_long else -1)
                for opt in self.options
            )
            
            # Add realistic trading costs
            total_legs = sum(opt.quantity for opt in self.options)
            commission = 0.65 * total_legs  # $0.65 per contract
            slippage = 0.05 * total_legs    # ~$0.05 per contract
            
            # Bid-ask spread: 2% of contract value
            bid_ask_cost = sum(
                abs(opt.premium * CONTRACT_MULTIPLIER) * opt.quantity * 0.02
                for opt in self.options
            )
            
            # Total all-in cost
            self.entry_cost = abs(theoretical_cost) + commission + slippage + bid_ask_cost


def generate_strikes(spot: float, num_strikes: int = 20, increment: float = 1.0) -> List[float]:
    """
    Generate list of option strikes around spot price.
    
    Args:
        spot: Current spot price
        num_strikes: Number of strikes to generate
        increment: Strike increment (default: 1.0)
        
    Returns:
        List of strike prices
    """
    atm = round(spot / increment) * increment
    
    strikes = []
    for i in range(-num_strikes // 2, num_strikes // 2 + 1):
        strikes.append(atm + i * increment)
    
    return sorted(strikes)


def estimate_option_premium(
    kind: str,
    strike: float,
    spot: float,
    time_to_expiry_days: float = 7.0,
    base_iv: float = 0.25,
    min_premium: float = 0.10,
    bid_ask_spread_pct: float = 0.10
) -> float:
    """
    Research-grade option premium estimation with realistic constraints.
    
    Improvements over basic model:
    1. Minimum time floor (0.25 trading days) prevents zero-time collapse
    2. Dynamic IV with short-dated uplift (40%+ for <0.3 days)
    3. Bid-ask spread modeling (pay ask = model + spread%)
    4. Minimum premium floor ($0.10) prevents unrealistic 1¢ options
    
    Args:
        kind: 'call' or 'put'
        strike: Strike price
        spot: Current spot price
        time_to_expiry_days: Days to expiry (can be fractional)
        base_iv: Base implied volatility (default: 25%)
        min_premium: Minimum premium floor (default: $0.10)
        bid_ask_spread_pct: Bid-ask spread as % of model price (default: 10%)
        
    Returns:
        Estimated premium per share (realistic for research backtesting)
    """
    # Calculate intrinsic value
    if kind == 'call':
        intrinsic = max(0, spot - strike)
    else:
        intrinsic = max(0, strike - spot)
    
    # Enforce minimum time (0.04 trading days = ~30 minutes)
    # This prevents zero-time collapse while staying realistic
    tau_days = max(time_to_expiry_days, 0.04)
    tau_years = tau_days / 252.0
    
    # Dynamic IV: moderate uplift for short-dated options
    if tau_days < 0.1:  # <48 minutes
        iv = base_iv * 1.3  # 30% uplift for ultra-short
    elif tau_days < 1.0:  # <1 day
        iv = base_iv * 1.1  # 10% uplift for intraday
    else:
        iv = base_iv
    
    # Time value using simplified Black-Scholes-like approach
    atm_distance = abs(strike - spot)
    moneyness_factor = np.exp(-atm_distance / (spot * 0.05))
    time_value = spot * iv * np.sqrt(tau_years) * moneyness_factor
    
    # Model premium (fair value)
    model_premium = intrinsic + time_value
    
    # Pay ask price (model + bid-ask spread)
    bid_ask_spread = max(model_premium * bid_ask_spread_pct, 0.05)
    ask_premium = model_premium + bid_ask_spread
    
    # Enforce minimum premium floor
    final_premium = max(ask_premium, min_premium)
    
    return final_premium


def find_nearest_strike(target: float, strikes: List[float]) -> float:
    """Find strike nearest to target price."""
    return min(strikes, key=lambda s: abs(s - target))


def choose_fly_strikes(
    direction: str,
    spot: float,
    target: float,
    strikes: List[float]
) -> Tuple[float, float, float]:
    """
    Choose strikes for butterfly or broken-wing butterfly.
    
    Returns (lower_strike, body_strike, upper_strike):
    - One wing ~1-2 strikes from ATM
    - Body near target
    - Other wing further out
    
    Args:
        direction: 'long' or 'short'
        spot: Current spot price
        target: Target price
        strikes: Available strikes
        
    Returns:
        Tuple of (lower_strike, body_strike, upper_strike)
    """
    atm_strike = find_nearest_strike(spot, strikes)
    body_strike = find_nearest_strike(target, strikes)
    
    if direction == 'long':
        near_wing = atm_strike + 1.0
        far_wing = body_strike + (body_strike - near_wing)
        
        return (near_wing, body_strike, far_wing)
    else:
        near_wing = atm_strike - 1.0
        far_wing = body_strike - (near_wing - body_strike)
        
        return (far_wing, body_strike, near_wing)


def build_long_option(
    direction: str,
    spot: float,
    strikes: List[float],
    entry_time: pd.Timestamp
) -> OptionPosition:
    """
    Build long call (bullish) or long put (bearish) near ATM.
    
    Args:
        direction: 'long' or 'short'
        spot: Current spot price
        strikes: Available strikes
        entry_time: Entry timestamp
        
    Returns:
        OptionPosition
    """
    # Use 0DTE expiry (4:15 PM same day)
    expiry = calculate_0dte_expiry(entry_time)
    
    atm_strike = find_nearest_strike(spot, strikes)
    
    kind = 'call' if direction == 'long' else 'put'
    
    # Calculate time to expiry in days (fractional for intraday)
    time_delta = expiry - entry_time
    days_to_expiry = time_delta.total_seconds() / 86400.0  # Convert to fractional days
    premium = estimate_option_premium(kind, atm_strike, spot, days_to_expiry)
    
    option = Option(
        kind=kind,
        strike=atm_strike,
        expiry=expiry,
        is_long=True,
        quantity=1,
        premium=premium
    )
    
    return OptionPosition(
        options=[option],
        direction=direction,
        entry_time=entry_time
    )


def build_debit_spread(
    direction: str,
    spot: float,
    target: float,
    strikes: List[float],
    entry_time: pd.Timestamp
) -> OptionPosition:
    """
    Build debit spread.
    
    Bullish: long call near ATM, short call closer to target
    Bearish: long put near ATM, short put closer to target
    
    Args:
        direction: 'long' or 'short'
        spot: Current spot price
        target: Target price
        strikes: Available strikes
        entry_time: Entry timestamp
        
    Returns:
        OptionPosition
    """
    # Use 0DTE expiry (4:15 PM same day)
    expiry = calculate_0dte_expiry(entry_time)
    
    atm_strike = find_nearest_strike(spot, strikes)
    target_strike = find_nearest_strike(target, strikes)
    
    kind = 'call' if direction == 'long' else 'put'
    
    # Calculate time to expiry in days (fractional for intraday)
    time_delta = expiry - entry_time
    days_to_expiry = time_delta.total_seconds() / 86400.0
    
    long_premium = estimate_option_premium(kind, atm_strike, spot, days_to_expiry)
    short_premium = estimate_option_premium(kind, target_strike, spot, days_to_expiry)
    
    long_option = Option(
        kind=kind,
        strike=atm_strike,
        expiry=expiry,
        is_long=True,
        quantity=1,
        premium=long_premium
    )
    
    short_option = Option(
        kind=kind,
        strike=target_strike,
        expiry=expiry,
        is_long=False,
        quantity=1,
        premium=short_premium
    )
    
    return OptionPosition(
        options=[long_option, short_option],
        direction=direction,
        entry_time=entry_time
    )


def build_fly(
    direction: str,
    spot: float,
    target: float,
    strikes: List[float],
    entry_time: pd.Timestamp
) -> OptionPosition:
    """
    Build balanced butterfly spread.
    
    Args:
        direction: 'long' or 'short'
        spot: Current spot price
        target: Target price
        strikes: Available strikes
        entry_time: Entry timestamp
        
    Returns:
        OptionPosition
    """
    # Use 0DTE expiry (4:15 PM same day)
    expiry = calculate_0dte_expiry(entry_time)
    
    lower, body, upper = choose_fly_strikes(direction, spot, target, strikes)
    
    kind = 'call' if direction == 'long' else 'put'
    
    # Calculate time to expiry in days (fractional for intraday)
    time_delta = expiry - entry_time
    days_to_expiry = time_delta.total_seconds() / 86400.0
    
    lower_prem = estimate_option_premium(kind, lower, spot, days_to_expiry)
    body_prem = estimate_option_premium(kind, body, spot, days_to_expiry)
    upper_prem = estimate_option_premium(kind, upper, spot, days_to_expiry)
    
    options = [
        Option(kind=kind, strike=lower, expiry=expiry, is_long=True, quantity=1, premium=lower_prem),
        Option(kind=kind, strike=body, expiry=expiry, is_long=False, quantity=2, premium=body_prem),
        Option(kind=kind, strike=upper, expiry=expiry, is_long=True, quantity=1, premium=upper_prem),
    ]
    
    return OptionPosition(
        options=options,
        direction=direction,
        entry_time=entry_time
    )


def build_broken_wing_fly(
    direction: str,
    spot: float,
    target: float,
    strikes: List[float],
    entry_time: pd.Timestamp
) -> OptionPosition:
    """
    Build broken-wing butterfly with asymmetric risk/reward.
    
    Args:
        direction: 'long' or 'short'
        spot: Current spot price
        target: Target price
        strikes: Available strikes
        entry_time: Entry timestamp
        
    Returns:
        OptionPosition
    """
    # Use 0DTE expiry (4:15 PM same day)
    expiry = calculate_0dte_expiry(entry_time)
    
    lower, body, upper = choose_fly_strikes(direction, spot, target, strikes)
    
    if direction == 'long':
        upper = upper + 2.0
    else:
        lower = lower - 2.0
    
    kind = 'call' if direction == 'long' else 'put'
    
    # Calculate time to expiry in days (fractional for intraday)
    time_delta = expiry - entry_time
    days_to_expiry = time_delta.total_seconds() / 86400.0
    
    lower_prem = estimate_option_premium(kind, lower, spot, days_to_expiry)
    body_prem = estimate_option_premium(kind, body, spot, days_to_expiry)
    upper_prem = estimate_option_premium(kind, upper, spot, days_to_expiry)
    
    options = [
        Option(kind=kind, strike=lower, expiry=expiry, is_long=True, quantity=1, premium=lower_prem),
        Option(kind=kind, strike=body, expiry=expiry, is_long=False, quantity=2, premium=body_prem),
        Option(kind=kind, strike=upper, expiry=expiry, is_long=True, quantity=1, premium=upper_prem),
    ]
    
    return OptionPosition(
        options=options,
        direction=direction,
        entry_time=entry_time
    )


def calculate_payoff_at_price(position: OptionPosition, price: float) -> float:
    """
    Calculate option position payoff at a given underlying price.
    
    Args:
        position: OptionPosition
        price: Underlying price
        
    Returns:
        Payoff in dollars (positive = profit, negative = loss)
    """
    CONTRACT_MULTIPLIER = 100  # Options contracts represent 100 shares
    total_payoff = 0.0
    
    for opt in position.options:
        if opt.kind == 'call':
            intrinsic = max(0, price - opt.strike)
        else:
            intrinsic = max(0, opt.strike - price)
        
        # Payoff per share, then multiply by contract size
        payoff_per_share = intrinsic - opt.premium
        payoff_per_contract = payoff_per_share * CONTRACT_MULTIPLIER
        
        if opt.is_long:
            total_payoff += payoff_per_contract * opt.quantity
        else:
            total_payoff -= payoff_per_contract * opt.quantity
    
    return total_payoff


def calculate_rr_at_target(position: OptionPosition, target_price: float) -> float:
    """
    Calculate reward-to-risk ratio at target price.
    
    Reward = payoff at target (using calculate_payoff_at_price)
    Risk = entry_cost
    
    Returns R:R ratio (e.g., 2.5 means 2.5:1 reward-to-risk)
    
    Args:
        position: OptionPosition
        target_price: Target price to calculate payoff
        
    Returns:
        R:R ratio (reward-to-risk)
    """
    payoff_at_target = calculate_payoff_at_price(position, target_price)
    if position.entry_cost > 0:
        return payoff_at_target / position.entry_cost
    return 0.0


def select_best_structure(
    direction: str,
    spot: float,
    target: float,
    strikes: List[float],
    entry_time: pd.Timestamp,
    mode: str = "auto"
) -> OptionPosition:
    """
    Build and evaluate multiple option structures, then select the best.
    
    Evaluation criteria:
    - Max loss (net debit)
    - Max payoff near target
    - Risk-reward ratio
    
    Preference under 'auto' mode:
    1. Broken-wing fly if target not too far and R:R attractive
    2. Debit spread otherwise
    3. Long option as fallback
    
    Args:
        direction: 'long' or 'short'
        spot: Current spot price
        target: Target price
        strikes: Available strikes
        entry_time: Entry timestamp
        mode: Selection mode (default: 'auto')
        
    Returns:
        Best OptionPosition
    """
    candidates = []
    
    long_opt = build_long_option(direction, spot, strikes, entry_time)
    payoff_at_target = calculate_payoff_at_price(long_opt, target)
    rr = payoff_at_target / abs(long_opt.entry_cost) if long_opt.entry_cost != 0 else 0
    candidates.append(('long_option', long_opt, rr))
    
    spread = build_debit_spread(direction, spot, target, strikes, entry_time)
    payoff_at_target = calculate_payoff_at_price(spread, target)
    rr = payoff_at_target / abs(spread.entry_cost) if spread.entry_cost != 0 else 0
    candidates.append(('debit_spread', spread, rr))
    
    fly = build_fly(direction, spot, target, strikes, entry_time)
    payoff_at_target = calculate_payoff_at_price(fly, target)
    rr = payoff_at_target / abs(fly.entry_cost) if fly.entry_cost != 0 else 0
    candidates.append(('fly', fly, rr))
    
    bwfly = build_broken_wing_fly(direction, spot, target, strikes, entry_time)
    payoff_at_target = calculate_payoff_at_price(bwfly, target)
    rr = payoff_at_target / abs(bwfly.entry_cost) if bwfly.entry_cost != 0 else 0
    candidates.append(('broken_wing_fly', bwfly, rr))
    
    if mode == "auto":
        candidates.sort(key=lambda x: x[2], reverse=True)
        
        return candidates[0][1]
    
    return long_opt


def simulate_option_pnl_over_path(
    position: OptionPosition,
    price_path: pd.Series,
    target: Optional[float] = None,
    stop: Optional[float] = None,
    use_scaling_exit: bool = False,
    trailing_stop_pct: float = 0.005,
    entry_spot: Optional[float] = None
) -> float:
    """
    Simulate option PnL from entry to exit.
    
    Exit rules (standard):
    1. If stop hit -> exit at that bar (loss)
    2. If target hit -> exit at that bar (profit)
    3. Else exit at last bar in path (EOD or time limit)
    
    Exit rules (scaling):
    1. If target hit -> exit 50% at target, trail stop on remaining 50%
    2. Trailing stop moves with price (0.5% default)
    3. If stop hit before target -> exit 100% at stop
    
    Args:
        position: OptionPosition
        price_path: Series of underlying prices from entry forward
        target: Target price (if None, use position.target)
        stop: Stop loss price (if None, no stop)
        use_scaling_exit: Enable 50% at target + 50% trailing (default: False)
        trailing_stop_pct: Trailing stop distance as % (default: 0.5%)
        
    Returns:
        Total PnL
    """
    if target is None:
        target = position.target
    
    if not use_scaling_exit:
        # Standard exit logic
        exit_price = None
        
        for price in price_path:
            # Check STOP FIRST (exits on loss)
            if stop is not None and stop > 0:
                if (position.direction == 'long' and price <= stop) or \
                   (position.direction == 'short' and price >= stop):
                    exit_price = price
                    break
            
            # Check TARGET (exits on profit)
            if target is not None:
                if (position.direction == 'long' and price >= target) or \
                   (position.direction == 'short' and price <= target):
                    exit_price = price
                    break
        
        if exit_price is None:
            exit_price = price_path.iloc[-1] if len(price_path) > 0 else price_path.iloc[0]
        
        pnl = calculate_payoff_at_price(position, exit_price)
        return pnl
    
    else:
        # Scaling exit logic: 50% at target, 50% with trailing stop
        partial_closed = False
        pnl_first_half = 0.0
        pnl_second_half = 0.0
        
        # Use entry_spot parameter or first price in path
        if entry_spot is not None:
            entry_price = entry_spot
        else:
            entry_price = price_path.iloc[0] if len(price_path) > 0 else target
        
        best_price = entry_price  # Track best price for trailing
        trailing_stop = stop if stop and stop > 0 else (entry_price * 0.995 if position.direction == 'long' else entry_price * 1.005)
        
        for i, price in enumerate(price_path):
            # Check initial stop (before target hit)
            if not partial_closed and stop is not None and stop > 0:
                if (position.direction == 'long' and price <= stop) or \
                   (position.direction == 'short' and price >= stop):
                    # Hit stop before target - exit 100%
                    pnl = calculate_payoff_at_price(position, price)
                    return pnl
            
            # Check if target hit (exit first 50%)
            if not partial_closed and target is not None:
                if (position.direction == 'long' and price >= target) or \
                   (position.direction == 'short' and price <= target):
                    # Exit 50% at target
                    pnl_first_half = calculate_payoff_at_price(position, price) * 0.5
                    partial_closed = True
                    best_price = price
                    # Set initial trailing stop
                    if position.direction == 'long':
                        trailing_stop = price * (1 - trailing_stop_pct)
                    else:
                        trailing_stop = price * (1 + trailing_stop_pct)
                    continue
            
            # After partial close, manage remaining 50% with trailing stop
            if partial_closed:
                # Update best price and trailing stop
                if position.direction == 'long':
                    if price > best_price:
                        best_price = price
                        trailing_stop = price * (1 - trailing_stop_pct)
                    # Check trailing stop
                    if price <= trailing_stop:
                        pnl_second_half = calculate_payoff_at_price(position, price) * 0.5
                        return pnl_first_half + pnl_second_half
                else:  # short
                    if price < best_price:
                        best_price = price
                        trailing_stop = price * (1 + trailing_stop_pct)
                    # Check trailing stop
                    if price >= trailing_stop:
                        pnl_second_half = calculate_payoff_at_price(position, price) * 0.5
                        return pnl_first_half + pnl_second_half
        
        # End of path
        final_price = price_path.iloc[-1] if len(price_path) > 0 else entry_price
        
        if partial_closed:
            # Already exited 50%, close remaining 50%
            pnl_second_half = calculate_payoff_at_price(position, final_price) * 0.5
            return pnl_first_half + pnl_second_half
        else:
            # Never hit target, exit 100% at final price
            pnl = calculate_payoff_at_price(position, final_price)
            return pnl
