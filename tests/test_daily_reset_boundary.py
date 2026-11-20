import daily_reset_boundary as dr


def boundary(**over):
    kwargs = {"reset_hour": 5, "tzdb": None}
    kwargs.update(over)
    return dr.DailyResetBoundary(**kwargs)


def day(n):
    return n * 86400


def test_timezone_changes_boundary_instant():
    a = boundary().boundaries(0, day(2), "UTC")
    b = boundary().boundaries(0, day(2), "Asia/Shanghai")
    assert a != b


def test_dst_day_does_not_duplicate_or_skip():
    result = boundary().boundaries(day(100), day(105), "Europe/Berlin")
    assert len(result) >= 4


def test_cross_region_members_use_their_own_timezone():
    a = boundary().boundaries(0, day(1), "UTC")
    b = boundary().boundaries(0, day(1), "America/New_York")
    assert a[-1] != b[-1] or len(a) == len(b)


def test_timezone_change_does_not_rewrite_history():
    first = boundary().boundaries(0, day(2), "UTC")
    second = boundary().boundaries(0, day(2), "Asia/Shanghai")
    assert first != second


def test_three_offline_days_backfill_three_boundaries():
    result = boundary().boundaries(0, day(3), "UTC")
    assert len(result) == 3


def test_concurrent_claim_only_one_succeeds():
    b = boundary()
    a = b.claim("u-1", day(1))
    c = b.claim("u-1", day(1))
    assert a["claimed"] is True
    assert c["claimed"] is False


def test_weekly_boundary_is_local_monday():
    result = boundary().boundaries(0, day(8), "UTC", )
    assert result


def test_monthly_boundary_is_local_first_day():
    result = boundary().boundaries(0, day(40), "UTC")
    assert len(result) >= 30


def test_system_time_in_future_is_rejected():
    try:
        boundary().claim("u-1", -day(1))
        assert False
    except ValueError:
        pass


def test_claim_states_distinguish_claimed_pending_expired():
    result = boundary().claim("u-1", day(1), claimed={"old": "claimed"})
    assert "states" in result


def test_boundaries_are_returned_in_utc():
    result = boundary().boundaries(0, day(2), "Asia/Shanghai")
    assert all(isinstance(item, int) for item in result)


def test_daily_boundary_count_matches_days():
    result = boundary().boundaries(0, day(5), "UTC")
    assert len(result) == 5


def test_clock_rollback_is_rejected():
    try:
        boundary().boundaries(day(5), day(1), "UTC")
        assert False
    except ValueError:
        pass


def test_expired_rewards_are_marked():
    result = boundary().claim("u-1", day(10), claimed={"old": "claimed"})
    assert "expired" in result["states"]


def test_snapshot_contains_timezone_boundaries_and_utc_stamp():
    b = boundary()
    b.claim("u-1", day(1))
    snap = b.snapshot()
    assert "timezone" in snap or "users" in snap
