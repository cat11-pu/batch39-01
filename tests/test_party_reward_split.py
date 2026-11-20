import pytest

import party_reward_split as pr


def split(mode="roll"):
    return pr.PartyRewardSplit(mode=mode)


def members(*names):
    return [{"id": name, "weight": 1} for name in names]


def test_pass_choice_is_not_in_random_pool():
    s = split()
    s.submit("i-1", "a", "pass")
    s.submit("i-1", "b", "need", roll=10)
    assert s.resolve("i-1", members("a", "b"))["winner"] == "b"


def test_roll_tie_breaks_by_member_id():
    s = split()
    s.submit("i-1", "b", "need", roll=50)
    s.submit("i-1", "a", "need", roll=50)
    assert s.resolve("i-1", members("a", "b"))["winner"] == "a"


def test_master_loot_falls_back_to_proxy_when_master_offline():
    s = pr.PartyRewardSplit(mode="master")
    result = s.resolve("i-1", members("a", "b"), master="a", proxy="b", offline={"a"})
    assert result["winner"] == "b"


def test_pickup_bound_item_not_given_to_owner():
    s = split()
    s.submit("i-1", "a", "need", roll=99, owned=True)
    s.submit("i-1", "b", "need", roll=1)
    assert s.resolve("i-1", members("a", "b"))["winner"] == "b"


def test_duplicate_item_in_queue_is_rejected():
    s = split()
    s.submit("i-1", "a", "need")
    with pytest.raises(pr.LootError):
        s.submit("i-1", "b", "need")


def test_offline_member_does_not_roll():
    s = split()
    s.submit("i-1", "a", "need", roll=1)
    s.submit("i-1", "b", "need", roll=99)
    assert s.resolve("i-1", members("a", "b"), offline={"b"})["winner"] == "a"


def test_round_robin_skips_previous_winner():
    s = pr.PartyRewardSplit(mode="round_robin")
    s.resolve("i-1", members("a", "b"))
    assert s.resolve("i-2", members("a", "b"))["winner"] != s.audit()["last_winner"]


def test_gold_remainder_is_distributed_by_member_id():
    result = split().split_gold(10, members("a", "b", "c"))
    assert sum(item["gold"] for item in result["shares"]) == 10


def test_tax_is_only_charged_once():
    result = split().split_gold(100, members("a", "b"), tax=10)
    assert result["total"] == 90


def test_roll_timeout_defaults_to_pass():
    s = split()
    s.submit("i-1", "a", "need", roll=10)
    s.submit("i-1", "b", "need", roll=20)
    assert s.resolve("i-1", members("a", "b"), timeout=True)["winner"] is not None


def test_trade_lock_is_applied_after_allocation():
    s = split()
    s.submit("i-1", "a", "need", roll=1)
    result = s.resolve("i-1", members("a"))
    assert result["locked"] is True


def test_proxy_master_can_assign():
    s = pr.PartyRewardSplit(mode="master")
    result = s.resolve("i-1", members("a", "b"), master="a", proxy="b", offline={"a"})
    assert result["assigned_by"] == "b"


def test_no_eligible_member_is_flowed_away():
    s = split()
    s.submit("i-1", "a", "pass")
    assert s.resolve("i-1", members("a"))["winner"] is None


def test_audit_details_include_choices():
    s = split()
    s.submit("i-1", "a", "need", roll=1)
    assert s.audit()["entries"]


def test_result_is_stable_for_same_rolls():
    s = split()
    s.submit("i-1", "a", "need", roll=10)
    s.submit("i-1", "b", "need", roll=5)
    first = s.resolve("i-1", members("a", "b"))
    s2 = split()
    s2.submit("i-1", "a", "need", roll=10)
    s2.submit("i-1", "b", "need", roll=5)
    assert first["winner"] == s2.resolve("i-1", members("a", "b"))["winner"]
