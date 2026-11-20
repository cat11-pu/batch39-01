import aggro_threat_table as at


def table(**over):
    kwargs = {"heal_factor": 0.5, "switch_ratio": 1.1, "decay": 0.05}
    kwargs.update(over)
    return at.AggroThreatTable(**kwargs)


def test_healing_threat_uses_factor_and_ignores_overheal():
    t = table(heal_factor=0.5)
    t.add("healer")
    t.heal("healer", effective=100, overheal=100)
    assert t.snapshot()["threat"]["healer"] == 50


def test_taunt_forces_target_then_returns_to_normal_choice():
    t = table()
    t.add("tank")
    t.add("dps")
    t.damage("tank", 100)
    t.damage("dps", 300)
    t.taunt("tank", duration=2, now=0)
    assert t.target() == "tank"
    t.update(now=3)
    assert t.target() == "dps"


def test_ranged_damage_is_discounted_by_distance():
    near = table()
    far = table()
    near.add("a")
    far.add("a")
    near.damage("a", 100, distance=0)
    far.damage("a", 100, distance=40)
    assert far.snapshot()["threat"]["a"] < near.snapshot()["threat"]["a"]


def test_out_of_sight_does_not_add_threat():
    t = table()
    t.add("a")
    t.damage("a", 100, visible=False)
    assert t.snapshot()["threat"]["a"] == 0


def test_target_switch_requires_ten_percent_lead():
    t = table(switch_ratio=1.1)
    t.add("a")
    t.add("b")
    t.damage("a", 100)
    t.damage("b", 105)
    assert t.target() == "a"
    t.damage("b", 20)
    assert t.target() == "b"


def test_threat_decays_out_of_combat():
    t = table(decay=0.5)
    t.add("a")
    t.damage("a", 100)
    t.update(now=1, in_combat=False)
    assert t.snapshot()["threat"]["a"] < 100


def test_reset_clears_everything():
    t = table()
    t.add("a")
    t.damage("a", 100)
    t.reset()
    assert t.snapshot()["threat"] == {}


def test_pet_threat_merges_to_owner():
    t = table()
    t.add("pet", owner="hunter")
    t.damage("pet", 100)
    assert "hunter" in t.snapshot()["threat"]


def test_duplicate_add_is_idempotent():
    t = table()
    t.add("a")
    t.add("a")
    t.damage("a", 10)
    assert t.snapshot()["threat"]["a"] == 10


def test_immune_taunt_is_ignored():
    t = table()
    t.add("tank")
    t.add("dps")
    t.damage("dps", 100)
    t.taunt("tank", duration=10, now=0, immune=True)
    assert t.target() == "dps"


def test_threat_sources_are_reported():
    t = table()
    t.add("a")
    t.damage("a", 50)
    t.heal("a", 20)
    assert "damage" in t.snapshot()["sources"]["a"]
    assert "heal" in t.snapshot()["sources"]["a"]


def test_threat_list_is_sorted_descending():
    t = table()
    for unit, damage in (("a", 10), ("b", 30), ("c", 20)):
        t.add(unit)
        t.damage(unit, damage)
    assert [item["unit"] for item in t.snapshot()["sorted"]] == ["b", "c", "a"]


def test_remove_unit_drops_its_threat():
    t = table()
    t.add("a")
    t.damage("a", 10)
    t.remove("a")
    assert "a" not in t.snapshot()["threat"]


def test_snapshot_is_detached():
    t = table()
    t.add("a")
    t.damage("a", 10)
    snap = t.snapshot()
    snap["threat"]["a"] = 999
    assert t.snapshot()["threat"]["a"] == 10


def test_taunt_expires_without_extra_attacks():
    t = table()
    t.add("tank")
    t.add("dps")
    t.damage("dps", 100)
    t.taunt("tank", duration=1, now=0)
    t.update(now=2)
    assert t.target() == "dps"
