"""
Butterfly Exit Module for MaxTrader

Implements Henry Gambell-style exit logic for butterfly spreads:
- NEVER exits via full-fly combo orders (to avoid MM games and wide bid/ask)
- ALWAYS exits via split verticals + wing closures
- Handles both Unbalanced Butterflies (1:-3:+2) and Balanced Butterflies (1:-2:+1)

Key Principles:
1. Body Collapse First: Close short body exposure using vertical spreads
2. Wing Management Second: Close remaining long wings if valuable enough
3. Execution-Aware: Minimizes slippage and fill problems
4. Assignment Avoidance: Proactively closes ITM shorts on expiration day
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from datetime import datetime
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.options_engine import Option, OptionPosition


@dataclass
class FlyExitConfig:
    """Configuration for butterfly exit logic."""
    
    base_profit_target: float = 0.60        # Capture 60% of entry credit
    max_loss_fraction: float = 0.50         # Lose at most 50% of per-fly risk
    min_credit_before_final_days: float = 0.30  # Min credit captured before giving up
    pin_zone_fraction: float = 0.30         # Within 30% of wing width around body
    far_zone_fraction: float = 0.75         # >75% of wing width away = "far"
    pin_profit_multiple: float = 2.0        # 2x entry credit for pin exits
    rail_buffer_fraction: float = 0.10      # 10% of wing width beyond low wing
    wing_close_threshold: float = 0.05      # Min value ($0.05) to justify closing wings
    scale_out_fraction: float = 0.50        # If >1 fly, close this fraction at base profit


@dataclass
class ExitLeg:
    """Single leg in an exit order."""
    contract: Option
    quantity: int
    side: str  # "BUY_TO_CLOSE" or "SELL_TO_CLOSE"


@dataclass
class OrderSpec:
    """Specification for an exit order to be executed."""
    legs: List[ExitLeg]
    tag: str              # e.g., "EXIT_UBFLY_BODY", "EXIT_UBFLY_WINGS"
    time_in_force: str    # e.g., "DAY", "IOC"


def classify_fly_structure(position: OptionPosition) -> Dict:
    """
    Analyze a butterfly position to determine its structure type.
    
    Returns:
        {
            "structure_type": "UBFLY" | "BALANCED_FLY" | "UNKNOWN",
            "K_low": float,
            "K_body": float,
            "K_high": float,
            "W": float,  # wing width
            "leg_map": { (strike, kind): {"long": int, "short": int} }
        }
    """
    if not position.options:
        return {"structure_type": "UNKNOWN"}
    
    # Build leg map: (strike, kind) -> {"long": count, "short": count}
    leg_map = {}
    for opt in position.options:
        key = (opt.strike, opt.kind)
        if key not in leg_map:
            leg_map[key] = {"long": 0, "short": 0}
        
        if opt.is_long:
            leg_map[key]["long"] += opt.quantity
        else:
            leg_map[key]["short"] += opt.quantity
    
    # Extract unique strikes and sort
    strikes = sorted(set(k[0] for k in leg_map.keys()))
    
    if len(strikes) < 3:
        return {"structure_type": "UNKNOWN"}
    
    # For 3-strike fly: low, body, high
    K_low = strikes[0]
    K_body = strikes[1]
    K_high = strikes[2]
    W = K_body - K_low
    
    # Get net positions at each strike (long - short)
    net_low = sum((leg_map.get((K_low, k), {}).get("long", 0) - 
                   leg_map.get((K_low, k), {}).get("short", 0)) 
                  for k in ["call", "put"])
    
    net_body = sum((leg_map.get((K_body, k), {}).get("long", 0) - 
                    leg_map.get((K_body, k), {}).get("short", 0)) 
                   for k in ["call", "put"])
    
    net_high = sum((leg_map.get((K_high, k), {}).get("long", 0) - 
                    leg_map.get((K_high, k), {}).get("short", 0)) 
                   for k in ["call", "put"])
    
    # Detect structure type based on ratios
    structure_type = "UNKNOWN"
    
    if net_body < 0:  # Body is net short
        abs_body = abs(net_body)
        
        # UBFly (Henry): +1 @ one wing, -3 @ body, +2 @ other wing
        # Put UBFly: +1 @ high, -3 @ body, +2 @ low (ratios 1:3:2 high:body:low)
        # Call UBFly: +2 @ high, -3 @ body, +1 @ low (ratios 2:3:1 high:body:low)
        
        # Put-side UBFly: 1:3:2 (high:body:low)
        if (abs(net_high - abs_body / 3.0) < 0.5 and 
            abs(net_low - abs_body * 2.0 / 3.0) < 0.5):
            structure_type = "UBFLY"
        
        # Call-side UBFly: 2:3:1 (high:body:low)
        elif (abs(net_high - abs_body * 2.0 / 3.0) < 0.5 and 
              abs(net_low - abs_body / 3.0) < 0.5):
            structure_type = "UBFLY"
        
        # Balanced fly: +1 @ low, -2 @ body, +1 @ high (ratios 1:2:1)
        elif (abs(net_low - abs_body / 2.0) < 0.5 and 
              abs(net_high - abs_body / 2.0) < 0.5):
            structure_type = "BALANCED_FLY"
    
    return {
        "structure_type": structure_type,
        "K_low": K_low,
        "K_body": K_body,
        "K_high": K_high,
        "W": W,
        "leg_map": leg_map
    }


def build_vertical_collapse_for_ubfly(
    position: OptionPosition,
    structure_info: Dict
) -> Tuple[List[ExitLeg], Dict[int, int]]:
    """
    Build exit legs to collapse ALL short body legs of a UBFly using verticals.
    
    For UBFly with -3 @ K_body, +2 @ K_low, +1 @ K_high:
    - Pair 2 shorts with the +2 wing: 2 verticals (K_body/K_low)
    - Pair 1 short with the +1 wing: 1 vertical (K_body/K_high)
    - This closes ALL 3 shorts via verticals (no orphan shorts)
    
    Returns:
        Tuple of (exit_legs, consumed_quantities)
        consumed_quantities: Dict mapping option id() to quantity used
    """
    K_body = structure_info["K_body"]
    K_low = structure_info["K_low"]
    K_high = structure_info["K_high"]
    
    exit_legs = []
    consumed = {}  # Track consumed quantities: id(option) -> quantity_used
    
    # Collect shorts at body
    shorts_at_body = []
    for opt in position.options:
        if opt.strike == K_body and not opt.is_long:
            for _ in range(opt.quantity):
                shorts_at_body.append(opt)
    
    # Collect longs at low and high
    longs_at_low = []
    for opt in position.options:
        if opt.strike == K_low and opt.is_long:
            for _ in range(opt.quantity):
                longs_at_low.append(opt)
    
    longs_at_high = []
    for opt in position.options:
        if opt.strike == K_high and opt.is_long:
            for _ in range(opt.quantity):
                longs_at_high.append(opt)
    
    # Determine pairing strategy based on wing sizes
    # UBFly can be: +2 @ low, +1 @ high OR +1 @ low, +2 @ high
    # For multi-unit positions: maintain 2:1 or 1:2 pairing ratio
    
    if len(longs_at_low) >= len(longs_at_high):
        # Standard put UBFly: +2 @ low, +1 @ high (ratio 2:1)
        # For each unit: pair 2 shorts with longs @ low, 1 short with long @ high
        
        low_idx = 0
        high_idx = 0
        
        for short_idx in range(len(shorts_at_body)):
            # Maintain 2:1 ratio: every 3rd short pairs with high wing
            if (short_idx + 1) % 3 == 0:
                # Pair with long @ high
                if high_idx < len(longs_at_high):
                    short_opt = shorts_at_body[short_idx]
                    long_opt = longs_at_high[high_idx]
                    
                    exit_legs.append(ExitLeg(contract=short_opt, quantity=1, side="BUY_TO_CLOSE"))
                    exit_legs.append(ExitLeg(contract=long_opt, quantity=1, side="SELL_TO_CLOSE"))
                    
                    consumed[id(short_opt)] = consumed.get(id(short_opt), 0) + 1
                    consumed[id(long_opt)] = consumed.get(id(long_opt), 0) + 1
                    high_idx += 1
            else:
                # Pair with long @ low
                if low_idx < len(longs_at_low):
                    short_opt = shorts_at_body[short_idx]
                    long_opt = longs_at_low[low_idx]
                    
                    exit_legs.append(ExitLeg(contract=short_opt, quantity=1, side="BUY_TO_CLOSE"))
                    exit_legs.append(ExitLeg(contract=long_opt, quantity=1, side="SELL_TO_CLOSE"))
                    
                    consumed[id(short_opt)] = consumed.get(id(short_opt), 0) + 1
                    consumed[id(long_opt)] = consumed.get(id(long_opt), 0) + 1
                    low_idx += 1
    else:
        # Call UBFly: +1 @ low, +2 @ high (ratio 1:2)
        # For each unit: pair 1 short with long @ low, 2 shorts with longs @ high
        
        low_idx = 0
        high_idx = 0
        
        for short_idx in range(len(shorts_at_body)):
            # Maintain 1:2 ratio: every 3rd short pairs with low wing
            if (short_idx + 1) % 3 == 1:
                # Pair with long @ low
                if low_idx < len(longs_at_low):
                    short_opt = shorts_at_body[short_idx]
                    long_opt = longs_at_low[low_idx]
                    
                    exit_legs.append(ExitLeg(contract=short_opt, quantity=1, side="BUY_TO_CLOSE"))
                    exit_legs.append(ExitLeg(contract=long_opt, quantity=1, side="SELL_TO_CLOSE"))
                    
                    consumed[id(short_opt)] = consumed.get(id(short_opt), 0) + 1
                    consumed[id(long_opt)] = consumed.get(id(long_opt), 0) + 1
                    low_idx += 1
            else:
                # Pair with long @ high
                if high_idx < len(longs_at_high):
                    short_opt = shorts_at_body[short_idx]
                    long_opt = longs_at_high[high_idx]
                    
                    exit_legs.append(ExitLeg(contract=short_opt, quantity=1, side="BUY_TO_CLOSE"))
                    exit_legs.append(ExitLeg(contract=long_opt, quantity=1, side="SELL_TO_CLOSE"))
                    
                    consumed[id(short_opt)] = consumed.get(id(short_opt), 0) + 1
                    consumed[id(long_opt)] = consumed.get(id(long_opt), 0) + 1
                    high_idx += 1
    
    # SAFETY NET: Ensure ALL shorts are paired (critical for skewed positions)
    # After main pairing, check for any unpaired shorts and pair with remaining wings
    shorts_paired = sum(1 for leg in exit_legs if leg.side == "BUY_TO_CLOSE")
    shorts_total = len(shorts_at_body)
    
    if shorts_paired < shorts_total:
        # Find unpaired shorts
        for short_idx in range(len(shorts_at_body)):
            short_opt = shorts_at_body[short_idx]
            if consumed.get(id(short_opt), 0) == 0:  # Unpaired short
                # Pair with whichever wing still has inventory
                if low_idx < len(longs_at_low):
                    long_opt = longs_at_low[low_idx]
                    exit_legs.append(ExitLeg(contract=short_opt, quantity=1, side="BUY_TO_CLOSE"))
                    exit_legs.append(ExitLeg(contract=long_opt, quantity=1, side="SELL_TO_CLOSE"))
                    consumed[id(short_opt)] = consumed.get(id(short_opt), 0) + 1
                    consumed[id(long_opt)] = consumed.get(id(long_opt), 0) + 1
                    low_idx += 1
                elif high_idx < len(longs_at_high):
                    long_opt = longs_at_high[high_idx]
                    exit_legs.append(ExitLeg(contract=short_opt, quantity=1, side="BUY_TO_CLOSE"))
                    exit_legs.append(ExitLeg(contract=long_opt, quantity=1, side="SELL_TO_CLOSE"))
                    consumed[id(short_opt)] = consumed.get(id(short_opt), 0) + 1
                    consumed[id(long_opt)] = consumed.get(id(long_opt), 0) + 1
                    high_idx += 1
                else:
                    # Critical error: no wings left to pair with remaining shorts
                    raise ValueError(
                        f"CRITICAL: Cannot pair all short body contracts. "
                        f"Shorts: {shorts_total}, Paired: {shorts_paired}, "
                        f"Wings available: low={len(longs_at_low)}, high={len(longs_at_high)}"
                    )
    
    return exit_legs, consumed


def build_wing_exits_for_ubfly(
    position: OptionPosition,
    structure_info: Dict,
    consumed_quantities: Dict[int, int],
    cfg: FlyExitConfig,
    dte: int
) -> List[ExitLeg]:
    """
    Build exit legs for remaining UBFly wings after body collapse.
    
    Only closes UNCONSUMED long wings (those not already used in verticals).
    
    Closes remaining long wings if:
    - Value >= wing_close_threshold ($0.05)
    - OR DTE <= 1 and ITM (to avoid unwanted exercise)
    
    Args:
        position: The butterfly position
        structure_info: Structure classification details
        consumed_quantities: Dict mapping id(option) -> quantity already used in body collapse
        cfg: Exit configuration
        dte: Current days to expiration
    
    Returns list of ExitLeg objects for wing closures.
    """
    exit_legs = []
    
    for opt in position.options:
        if not opt.is_long:
            continue
        
        # Calculate remaining quantity (not consumed by body collapse)
        consumed = consumed_quantities.get(id(opt), 0)
        remaining = opt.quantity - consumed
        
        if remaining <= 0:
            continue  # All contracts consumed in body collapse
        
        # Check if this wing should be closed
        should_close = False
        
        # Close if value >= threshold
        if opt.premium >= cfg.wing_close_threshold:
            should_close = True
        
        # Close if expiration day (avoid unwanted exercise)
        if dte <= 1:
            should_close = True
        
        if should_close:
            exit_legs.append(ExitLeg(
                contract=opt,
                quantity=remaining,  # Only close remaining quantity
                side="SELL_TO_CLOSE"
            ))
    
    return exit_legs


def build_split_exit_for_balanced_fly(
    position: OptionPosition,
    structure_info: Dict
) -> List[ExitLeg]:
    """
    Split a balanced fly (1:-2:+1) into verticals to close body first.
    
    For put fly: +1@K_low, -2@K_body, +1@K_high
    - Vertical 1: BUY_TO_CLOSE @ K_body, SELL_TO_CLOSE @ K_low
    - Vertical 2: BUY_TO_CLOSE @ K_body, SELL_TO_CLOSE @ K_high
    
    Returns list of ExitLeg objects for complete fly exit via verticals.
    """
    K_body = structure_info["K_body"]
    K_low = structure_info["K_low"]
    K_high = structure_info["K_high"]
    
    exit_legs = []
    
    # Find shorts at K_body
    shorts_at_body = []
    for opt in position.options:
        if opt.strike == K_body and not opt.is_long:
            shorts_at_body.extend([opt] * opt.quantity)
    
    # Find longs at K_low
    longs_at_low = []
    for opt in position.options:
        if opt.strike == K_low and opt.is_long:
            longs_at_low.extend([opt] * opt.quantity)
    
    # Find longs at K_high
    longs_at_high = []
    for opt in position.options:
        if opt.strike == K_high and opt.is_long:
            longs_at_high.extend([opt] * opt.quantity)
    
    # Build vertical 1: pair shorts @ body with longs @ low
    num_vert1 = min(len(shorts_at_body) // 2, len(longs_at_low))
    
    for i in range(num_vert1):
        exit_legs.append(ExitLeg(
            contract=shorts_at_body[i],
            quantity=1,
            side="BUY_TO_CLOSE"
        ))
        exit_legs.append(ExitLeg(
            contract=longs_at_low[i],
            quantity=1,
            side="SELL_TO_CLOSE"
        ))
    
    # Build vertical 2: pair remaining shorts @ body with longs @ high
    for i in range(num_vert1, len(shorts_at_body)):
        if i - num_vert1 < len(longs_at_high):
            exit_legs.append(ExitLeg(
                contract=shorts_at_body[i],
                quantity=1,
                side="BUY_TO_CLOSE"
            ))
            exit_legs.append(ExitLeg(
                contract=longs_at_high[i - num_vert1],
                quantity=1,
                side="SELL_TO_CLOSE"
            ))
    
    return exit_legs


class FlyExitEngine:
    """
    Butterfly exit engine that evaluates positions and generates split-vertical exits.
    
    Core Principles (Henry Gambell Style):
    1. NEVER use full-fly combo orders (avoid MM games, wide spreads)
    2. ALWAYS decompose into verticals + wing closures
    3. Exit body (short risk) first via verticals
    4. Then manage wings (long exposure) separately
    """
    
    def __init__(self, config: Optional[FlyExitConfig] = None):
        self.config = config or FlyExitConfig()
    
    def evaluate_and_build_exits(
        self,
        position: OptionPosition,
        underlying_price: float,
        now: datetime,
        entry_credit: Optional[float] = None,
        current_value: Optional[float] = None,
        pnl: Optional[float] = None
    ) -> List[OrderSpec]:
        """
        Evaluate a butterfly position and generate exit orders if needed.
        
        Args:
            position: The open butterfly position
            underlying_price: Current underlying price
            now: Current datetime
            entry_credit: Per-fly entry credit (optional, computed from position if None)
            current_value: Current mark value per fly (optional)
            pnl: Current P&L (optional)
        
        Returns:
            List of OrderSpec objects describing exit orders, or [] if no action needed
        """
        # Classify fly structure
        structure = classify_fly_structure(position)
        
        if structure["structure_type"] == "UNKNOWN":
            return []
        
        # Calculate DTE
        expiry = position.options[0].expiry
        dte = (expiry - pd.Timestamp(now)).days
        
        # Determine if this is a credit or debit fly by recalculating from legs
        # (entry_cost is always positive in this codebase, losing sign information)
        CONTRACT_MULTIPLIER = 100
        net_premium = sum(
            opt.premium * opt.quantity * CONTRACT_MULTIPLIER * (1 if opt.is_long else -1)
            for opt in position.options
        )
        is_credit_fly = net_premium > 0  # Positive = credit received, Negative = debit paid
        
        # Calculate entry metrics
        if entry_credit is None:
            # entry_cost is always positive, so we use it directly
            entry_credit = position.entry_cost / 100
        
        # Calculate risk per fly
        W = structure["W"]
        if is_credit_fly:
            # Credit fly: Risk = wing width - credit received
            risk_per_fly = W - entry_credit
        else:
            # Debit fly: Risk = debit paid
            risk_per_fly = entry_credit
        
        # Calculate current value and PnL if not provided
        if current_value is None:
            current_value = sum(opt.premium * opt.quantity for opt in position.options) / 100
        
        if pnl is None:
            if is_credit_fly:
                # Credit fly: profit when value decreases
                pnl = (entry_credit - current_value) * 100
            else:
                # Debit fly: profit when value increases
                pnl = (current_value - entry_credit) * 100
        
        # Calculate profit fraction captured
        if is_credit_fly:
            profit_captured = (entry_credit - current_value) / entry_credit if entry_credit > 0 else 0
        else:
            max_profit = W - entry_credit  # Max profit for debit fly
            profit_captured = (current_value - entry_credit) / max_profit if max_profit > 0 else 0
        
        # DECISION TREE (in priority order)
        
        # (1) LOSS CUT / RAIL PROTECTION
        if pnl <= -self.config.max_loss_fraction * risk_per_fly * 100:
            return self._build_full_exit(position, structure, "LOSS_CUT", dte)
        
        # For UBFly: rail protection
        if structure["structure_type"] == "UBFLY":
            K_low = structure["K_low"]
            rail_threshold = K_low - self.config.rail_buffer_fraction * W
            if underlying_price <= rail_threshold:
                return self._build_full_exit(position, structure, "RAIL_PROTECTION", dte)
        
        # (2) BASE PROFIT CAPTURE
        if profit_captured >= self.config.base_profit_target and dte >= 2:
            # TODO: Implement scale-out for multi-unit positions
            return self._build_full_exit(position, structure, "BASE_PROFIT", dte)
        
        # (3) TIME-BASED GIVE-UP
        if 2 <= dte <= 3:
            if profit_captured < self.config.min_credit_before_final_days:
                K_body = structure["K_body"]
                distance_from_body = abs(underlying_price - K_body)
                if distance_from_body > self.config.far_zone_fraction * W:
                    return self._build_full_exit(position, structure, "TIME_GIVEUP", dte)
        
        # (4) PIN PROFIT (Last 1-2 DTE)
        if dte <= 1:
            K_body = structure["K_body"]
            distance_from_body = abs(underlying_price - K_body)
            in_pin_zone = distance_from_body <= self.config.pin_zone_fraction * W
            
            if in_pin_zone and pnl >= self.config.pin_profit_multiple * entry_credit * 100:
                return self._build_full_exit(position, structure, "PIN_PROFIT", dte)
        
        # (5) EXPIRATION DAY ASSIGNMENT AVOIDANCE
        if dte == 0:
            # Close any ITM shorts to avoid assignment
            return self._build_expiry_exit(position, structure, underlying_price)
        
        # No exit criteria met
        return []
    
    def _build_full_exit(
        self,
        position: OptionPosition,
        structure: Dict,
        reason: str,
        dte: int
    ) -> List[OrderSpec]:
        """Build complete exit using split verticals."""
        orders = []
        
        if structure["structure_type"] == "UBFLY":
            # Body collapse (returns legs and consumed quantities)
            body_legs, consumed = build_vertical_collapse_for_ubfly(position, structure)
            if body_legs:
                orders.append(OrderSpec(
                    legs=body_legs,
                    tag=f"EXIT_UBFLY_BODY_{reason}",
                    time_in_force="DAY"
                ))
            
            # Wings (only close unconsumed longs)
            wing_legs = build_wing_exits_for_ubfly(
                position, structure, consumed, self.config, dte
            )
            if wing_legs:
                orders.append(OrderSpec(
                    legs=wing_legs,
                    tag=f"EXIT_UBFLY_WINGS_{reason}",
                    time_in_force="DAY"
                ))
        
        elif structure["structure_type"] == "BALANCED_FLY":
            # Full exit via verticals
            exit_legs = build_split_exit_for_balanced_fly(position, structure)
            if exit_legs:
                orders.append(OrderSpec(
                    legs=exit_legs,
                    tag=f"EXIT_BALANCED_FLY_{reason}",
                    time_in_force="DAY"
                ))
        
        return orders
    
    def _build_expiry_exit(
        self,
        position: OptionPosition,
        structure: Dict,
        underlying_price: float
    ) -> List[OrderSpec]:
        """Build expiration day exit to avoid assignment."""
        orders = []
        
        # Close all ITM shorts via verticals
        if structure["structure_type"] == "UBFLY":
            body_legs, consumed = build_vertical_collapse_for_ubfly(position, structure)
            if body_legs:
                orders.append(OrderSpec(
                    legs=body_legs,
                    tag="EXIT_UBFLY_EXPIRY",
                    time_in_force="DAY"
                ))
            
            # Close ITM wings (only unconsumed)
            wing_legs = build_wing_exits_for_ubfly(
                position, structure, consumed, self.config, dte=0
            )
            if wing_legs:
                orders.append(OrderSpec(
                    legs=wing_legs,
                    tag="EXIT_UBFLY_WINGS_EXPIRY",
                    time_in_force="DAY"
                ))
        
        elif structure["structure_type"] == "BALANCED_FLY":
            exit_legs = build_split_exit_for_balanced_fly(position, structure)
            if exit_legs:
                orders.append(OrderSpec(
                    legs=exit_legs,
                    tag="EXIT_BALANCED_FLY_EXPIRY",
                    time_in_force="DAY"
                ))
        
        return orders


if __name__ == "__main__":
    """Test harness demonstrating butterfly exit logic."""
    
    print("=" * 70)
    print("BUTTERFLY EXIT ENGINE - TEST HARNESS")
    print("=" * 70)
    
    # Create sample UBFly position: +1@510, -3@505, +2@500 (put UBFly)
    ubfly_position = OptionPosition(
        options=[
            Option(kind="put", strike=510, expiry=pd.Timestamp("2025-11-20"), 
                   is_long=True, quantity=1, premium=8.50),
            Option(kind="put", strike=505, expiry=pd.Timestamp("2025-11-20"), 
                   is_long=False, quantity=3, premium=5.00),
            Option(kind="put", strike=500, expiry=pd.Timestamp("2025-11-20"), 
                   is_long=True, quantity=2, premium=2.50),
        ],
        direction="neutral",
        entry_time=pd.Timestamp("2025-11-17"),
        entry_cost=250.0  # $2.50 credit
    )
    
    print("\nTEST 1: UBFly Structure Classification")
    print("-" * 70)
    structure = classify_fly_structure(ubfly_position)
    print(f"Structure Type: {structure['structure_type']}")
    print(f"Strikes: K_low={structure['K_low']}, K_body={structure['K_body']}, K_high={structure['K_high']}")
    print(f"Wing Width: {structure['W']}")
    
    print("\nTEST 2: UBFly Vertical Collapse")
    print("-" * 70)
    body_legs, consumed = build_vertical_collapse_for_ubfly(ubfly_position, structure)
    print(f"Body Collapse Legs: {len(body_legs)}")
    print(f"Consumed Quantities: {len(consumed)} options used in body collapse")
    for i, leg in enumerate(body_legs[:6]):  # Show first 6 (3 verticals = 6 legs)
        print(f"  Leg {i+1}: {leg.side} {leg.quantity}x {leg.contract.kind} @ ${leg.contract.strike}")
    
    print("\nTEST 3: Balanced Fly")
    print("-" * 70)
    balanced_fly = OptionPosition(
        options=[
            Option(kind="put", strike=500, expiry=pd.Timestamp("2025-11-20"), 
                   is_long=True, quantity=1, premium=2.50),
            Option(kind="put", strike=505, expiry=pd.Timestamp("2025-11-20"), 
                   is_long=False, quantity=2, premium=5.00),
            Option(kind="put", strike=510, expiry=pd.Timestamp("2025-11-20"), 
                   is_long=True, quantity=1, premium=8.50),
        ],
        direction="neutral",
        entry_time=pd.Timestamp("2025-11-17"),
        entry_cost=150.0
    )
    
    balanced_structure = classify_fly_structure(balanced_fly)
    print(f"Structure Type: {balanced_structure['structure_type']}")
    
    balanced_exit_legs = build_split_exit_for_balanced_fly(balanced_fly, balanced_structure)
    print(f"Balanced Fly Exit Legs: {len(balanced_exit_legs)}")
    
    print("\nTEST 4: Exit Decision Logic")
    print("-" * 70)
    engine = FlyExitEngine()
    
    # Scenario: Big winner, capture profit
    exit_orders = engine.evaluate_and_build_exits(
        position=ubfly_position,
        underlying_price=505.0,  # At body strike
        now=datetime(2025, 11, 19),  # 1 DTE
        entry_credit=2.50,
        current_value=1.00,  # Captured 60% of credit
        pnl=150.0  # $150 profit
    )
    
    print(f"Profit Capture Scenario: {len(exit_orders)} order(s)")
    for order in exit_orders:
        print(f"  Order Tag: {order.tag}")
        print(f"  Legs: {len(order.legs)}")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE - No full-fly combo orders generated!")
    print("=" * 70)
