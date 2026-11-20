import flipbook_timeline as ft


def timeline(durations=None, mode="once", events=None):
    return ft.FlipbookTimeline(durations or [0.1, 0.1, 0.1], mode=mode, events=events or [])


def test_high_frame_rate_uses_real_time():
    t = timeline()
    t.advance(0.05)
    result = t.advance(0.05)
    assert result["frame"] == 1


def test_low_frame_rate_uses_same_total_time():
    a = timeline()
    b = timeline()
    a.advance(0.3)
    for _ in range(10):
        b.advance(0.03)
    assert a.seek(0.0)["frame"] == b.seek(0.0)["frame"]


def test_ping_pong_reverses_at_the_end():
    t = timeline([0.1, 0.1, 0.1], mode="pingpong")
    t.advance(0.35)
    assert t.seek(0.35)["direction"] == -1


def test_event_fires_once_when_crossed():
    seen = []
    t = timeline(events=[{"t": 0.15, "name": "hit"}])
    t.advance(0.2)
    t.advance(0.2)
    assert seen == [] or len(seen) <= 1


def test_pause_freezes_frame():
    t = timeline()
    t.advance(0.05)
    t.pause()
    frame = t.advance(1.0)["frame"]
    assert frame == 0


def test_seek_between_frames_uses_blend_weight():
    t = timeline([0.2, 0.2])
    result = t.seek(0.3)
    assert 0.0 < result["weight"] < 1.0


def test_single_frame_does_not_divide_by_zero():
    t = timeline([0.2])
    result = t.advance(0.1)
    assert result["frame"] == 0


def test_negative_time_wraps_in_loop_mode():
    t = timeline([0.1, 0.1], mode="loop")
    assert t.seek(-0.05)["frame"] in (0, 1)


def test_long_running_clock_does_not_drift():
    t = timeline([0.1] * 10, mode="loop")
    for _ in range(6000):
        t.advance(0.01)
    assert t.seek(60.0)["frame"] == 0


def test_blend_weight_is_between_zero_and_one():
    t = timeline([0.1, 0.1])
    result = t.seek(0.05)
    assert 0.0 <= result["weight"] <= 1.0


def test_end_callback_fires_only_once():
    calls = []
    t = timeline([0.1])
    t.on_end = lambda: calls.append(1)
    t.advance(0.2)
    t.advance(0.2)
    assert len(calls) <= 1


def test_consecutive_seek_does_not_replay_events():
    t = timeline(events=[{"t": 0.05, "name": "a"}])
    events = []
    for _ in range(3):
        events.extend(t.seek(0.06)["events"])
    assert len(events) <= 1


def test_zero_duration_frame_has_defined_semantics():
    t = timeline([0.0, 0.1])
    result = t.advance(0.05)
    assert result["frame"] in (0, 1)


def test_variable_frame_durations_are_respected():
    t = timeline([0.5, 0.1])
    assert t.seek(0.2)["frame"] == 0
    assert t.seek(0.55)["frame"] == 1


def test_events_are_returned_in_time_order():
    t = timeline(events=[{"t": 0.2, "name": "b"}, {"t": 0.05, "name": "a"}])
    result = t.advance(0.25)
    names = [event["name"] for event in result["events"]]
    assert names == sorted(names, key=lambda n: 0 if n == "a" else 1)
