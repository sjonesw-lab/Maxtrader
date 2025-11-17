"""
Execution engine for MaxTrader options trading system.

Handles order routing, fill simulation, and position management.
"""

from .butterfly_exit_router import ButterflyExitRouter, ExitResult
from .order_executor import OrderExecutor, OrderFill

__all__ = [
    'ButterflyExitRouter',
    'ExitResult',
    'OrderExecutor',
    'OrderFill',
]
