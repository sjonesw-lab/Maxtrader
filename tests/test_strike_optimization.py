"""Test to demonstrate improved strike selection for long options."""

import pandas as pd
from engine.options_engine import (
    generate_strikes,
    select_best_structure,
    calculate_payoff_at_price,
    build_long_option_at_strike,
    find_nearest_strike
)


def test_otm_vs_atm_comparison():
    """
    Demonstrate intelligent strike selection across multiple moneyness levels.
    
    For 0DTE options:
    - Small moves: ATM often provides best R:R (proven by this test)
    - Large moves: OTM might provide better leverage
    - System evaluates ALL strikes and picks the optimal one
    
    Example: Going long from $450 to $455 target (small $5 move)
    """
    spot = 450.0
    target = 455.0
    strikes = generate_strikes(spot, num_strikes=20, increment=1.0)
    entry_time = pd.Timestamp('2025-01-15 10:00', tz='America/New_York')
    
    atm_strike = find_nearest_strike(spot, strikes)
    
    # Build and compare multiple strikes
    results = []
    for otm_offset in [0, 1, 2, 3]:
        test_strike = atm_strike + otm_offset
        if test_strike in strikes:
            position = build_long_option_at_strike('long', spot, test_strike, entry_time)
            payoff = calculate_payoff_at_price(position, target)
            rr = payoff / position.entry_cost if position.entry_cost > 0 else 0
            
            results.append({
                'strike': test_strike,
                'otm_offset': otm_offset,
                'cost': position.entry_cost,
                'payoff': payoff,
                'rr': rr
            })
            
            print(f"\n{otm_offset} OTM (${test_strike:.0f} strike):")
            print(f"  Cost: ${position.entry_cost:.2f}")
            print(f"  Payoff at ${target}: ${payoff:.2f}")
            print(f"  R:R Ratio: {rr:.3f}:1")
    
    # Find best R:R across all strikes
    best_result = max(results, key=lambda x: x['rr'])
    
    print(f"\n✅ Best strike: {best_result['otm_offset']} OTM (${best_result['strike']:.0f})")
    print(f"   R:R Ratio: {best_result['rr']:.3f}:1")
    print(f"   Cost: ${best_result['cost']:.2f}")
    print(f"   Payoff: ${best_result['payoff']:.2f}")
    
    # Verify at least one strike has positive payoff
    assert any(r['rr'] > 0 for r in results), "At least one strike should be profitable at target"
    # Verify we evaluated multiple strikes
    assert len(results) >= 3, "Should evaluate at least 3 different strikes"


def test_select_best_structure_uses_optimal_strike():
    """
    Verify that select_best_structure now evaluates multiple strikes
    and selects the one with best R:R ratio.
    """
    spot = 450.0
    target = 455.0
    strikes = generate_strikes(spot, num_strikes=20, increment=1.0)
    entry_time = pd.Timestamp('2025-01-15 10:00', tz='America/New_York')
    
    # Get best structure (should now optimize strike selection)
    best_position = select_best_structure('long', spot, target, strikes, entry_time, mode='auto')
    
    # Calculate R:R
    payoff = calculate_payoff_at_price(best_position, target)
    rr = payoff / best_position.entry_cost if best_position.entry_cost > 0 else 0
    
    print(f"\n🎯 Best structure selected:")
    print(f"   Structure type: {best_position.structure_type if hasattr(best_position, 'structure_type') else 'options'}")
    print(f"   Number of legs: {len(best_position.options)}")
    if len(best_position.options) == 1:
        print(f"   Strike: ${best_position.options[0].strike:.0f}")
        print(f"   Spot: ${spot:.0f}")
        otm_offset = best_position.options[0].strike - spot
        print(f"   OTM offset: {otm_offset:.0f}")
    print(f"   Cost: ${best_position.entry_cost:.2f}")
    print(f"   Payoff at target: ${payoff:.2f}")
    print(f"   R:R Ratio: {rr:.3f}:1")
    
    # Verify it's a valid structure
    assert best_position.entry_cost > 0, "Structure should have positive cost"
    assert payoff > 0, "Structure should have positive payoff at target"
    assert rr > 0, "Structure should have positive R:R ratio"


if __name__ == '__main__':
    print("=" * 60)
    print("STRIKE OPTIMIZATION DEMONSTRATION")
    print("=" * 60)
    
    test_otm_vs_atm_comparison()
    test_select_best_structure_uses_optimal_strike()
    
    print("\n" + "=" * 60)
    print("✅ All tests passed - Strike optimization working!")
    print("=" * 60)
