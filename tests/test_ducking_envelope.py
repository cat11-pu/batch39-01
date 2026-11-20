import ducking_envelope as de


def env(**over):
    kwargs = {"attack": 0.1, "release": 0.3, "hold": 0.0}
    kwargs.update(over)
    return de.DuckingEnvelope(**kwargs)


def test_multiple_sources_use_deepest_gain_per_bus():
    e = env()
    e.add_source("voice", "music", priority=1, depth=0.5)
    e.add_source("explosion", "music", priority=2, depth=0.2)
    assert e.update(1.0)["gain"]["music"] == 0.2


def test_high_priority_end_restores_lower_source_depth():
    e = env()
    e.add_source("voice", "music", 1, 0.5)
    e.add_source("explosion", "music", 2, 0.2)
    e.remove_source("explosion")
    e.update(1.0)
    assert e.update(0.0)["gain"]["music"] == 0.5


def test_explosion_end_does_not_restore_music_while_voice_active():
    e = env()
    e.add_source("voice", "music", 1, 0.5)
    e.add_source("explosion", "music", 2, 0.2)
    e.remove_source("explosion")
    assert e.update(0.0)["gain"]["music"] < 0.5


def test_tinnitus_and_voice_stack_by_deepest():
    e = env()
    e.add_source("voice", "music", 1, 0.5)
    e.add_source("tinnitus", "music", 3, 0.1)
    assert e.update(0.5)["gain"]["music"] == 0.1


def test_attack_time_smooths_gain_down():
    e = env(attack=0.1)
    e.add_source("voice", "music", 1, 0.5)
    mid = e.update(0.05)["gain"]["music"]
    assert 0.5 < mid < 1.0


def test_release_time_smooths_gain_up():
    e = env(release=0.2)
    e.add_source("voice", "music", 1, 0.5)
    e.update(1.0)
    e.remove_source("voice")
    mid = e.update(0.05)["gain"]["music"]
    assert 0.5 < mid < 1.0


def test_existing_bus_fade_is_multiplied_once():
    e = env()
    e.set_bus_gain("music", 0.5)
    e.add_source("voice", "music", 1, 0.5)
    assert e.update(1.0)["gain"]["music"] == 0.25


def test_voice_bus_is_not_ducked_by_music_source():
    e = env()
    e.add_source("voice", "music", 1, 0.5)
    assert e.update(1.0)["gain"]["voice"] == 1.0


def test_gain_is_clipped_to_safe_range():
    e = env()
    e.set_bus_gain("music", 2.0)
    e.add_source("voice", "music", 1, 0.0)
    assert 0.0 <= e.update(1.0)["gain"]["music"] <= 1.0


def test_pause_freezes_envelope_timer():
    e = env()
    e.add_source("voice", "music", 1, 0.5)
    before = e.update(0.05, paused=True)["gain"]["music"]
    after = e.update(0.05, paused=True)["gain"]["music"]
    assert before == after


def test_two_voice_sources_keep_ducking_until_both_end():
    e = env()
    e.add_source("v1", "music", 1, 0.4)
    e.add_source("v2", "music", 1, 0.3)
    e.remove_source("v1")
    assert e.update(1.0)["gain"]["music"] == 0.3


def test_release_curve_is_monotonic():
    e = env(release=0.2)
    e.add_source("voice", "music", 1, 0.5)
    e.update(1.0)
    e.remove_source("voice")
    values = [e.update(0.05)["gain"]["music"] for _ in range(5)]
    assert values == sorted(values)


def test_deepest_source_wins_not_product():
    e = env()
    e.add_source("a", "music", 1, 0.5)
    e.add_source("b", "music", 1, 0.5)
    assert e.update(1.0)["gain"]["music"] == 0.5


def test_frame_rate_does_not_change_final_gain():
    a = env(attack=0.2)
    b = env(attack=0.2)
    for e in (a, b):
        e.add_source("voice", "music", 1, 0.5)
    a.update(0.2)
    for _ in range(4):
        b.update(0.05)
    assert abs(a.update(0.0)["gain"]["music"] - b.update(0.0)["gain"]["music"]) < 1e-6


def test_output_reports_target_gain_and_remaining_time():
    e = env()
    e.add_source("voice", "music", 1, 0.5)
    result = e.update(0.1)
    assert "target" in result and "remaining" in result
