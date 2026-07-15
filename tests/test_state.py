from state import MarketState, Position, Side


def test_market_state_defaults_include_safety_fields():
    state = MarketState()
    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
    assert state.last_reset_date is None
    assert state.daily_starting_balance is None


def test_state_has_no_macro_gate_fields():
    state = MarketState()
    assert not hasattr(state, "macro_blocks_longs")
    assert not hasattr(state, "macro_blocks_shorts")


def test_state_has_no_order_book_snapshot_buffer():
    state = MarketState()
    assert not hasattr(state, "ob_snapshots")


def test_position_defaults_include_fee_tracking_fields():
    pos = Position(
        side=Side.LONG,
        entry_price=100.0,
        size=1.0,
        entry_time=0.0,
        stop_loss=95.0,
        tp1=110.0,
        initial_atr=2.0,
        initial_sl_distance=5.0,
    )
    assert pos.fees_paid == 0.0
    assert pos.realized_pnl == 0.0
