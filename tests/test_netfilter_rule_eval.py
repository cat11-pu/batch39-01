import pytest

import netfilter_rule_eval as nf


def rule(chain="INPUT", src=None, dst=None, port=None, proto=None, state=None, iface=None, target="ACCEPT"):
    return {"chain": chain, "src": src, "dst": dst, "port": port, "proto": proto, "state": state, "iface": iface, "target": target}


def packet(src="10.0.0.1", dst="10.0.0.2", port=80, proto="tcp", state="NEW", iface="eth0"):
    return {"src": src, "dst": dst, "port": port, "proto": proto, "state": state, "iface": iface}


def evaluator(rules, **over):
    kwargs = {"default_policy": "DROP", "max_depth": 16}
    kwargs.update(over)
    return nf.NetfilterRuleEval(rules, **kwargs)


def test_return_resumes_next_rule_in_caller_chain():
    rules = [rule(chain="INPUT", target="MYCHAIN"), rule(chain="MYCHAIN", target="RETURN"), rule(chain="INPUT", target="DROP")]
    result = evaluator(rules).evaluate(packet())
    assert result["action"] == "DROP"


def test_jump_cycle_is_rejected():
    rules = [rule(chain="A", target="B"), rule(chain="B", target="A")]
    with pytest.raises(nf.RuleError) as exc:
        evaluator(rules).evaluate(packet())
    assert exc.value.code == "jump_cycle"


def test_first_matching_rule_wins_in_order():
    rules = [rule(target="DROP"), rule(target="ACCEPT")]
    assert evaluator(rules).evaluate(packet())["action"] == "DROP"


def test_source_network_host_bits_are_normalized():
    rules = [rule(src="10.0.0.5/8", target="ACCEPT")]
    assert evaluator(rules).evaluate(packet(src="10.9.9.9"))["action"] == "ACCEPT"


def test_invalid_port_range_is_rejected():
    with pytest.raises(nf.RuleError):
        evaluator([rule(port=(100, 10))])


def test_protocol_case_is_normalized():
    rules = [rule(proto="TCP", target="ACCEPT")]
    assert evaluator(rules).evaluate(packet(proto="tcp"))["action"] == "ACCEPT"


def test_connection_state_must_match():
    rules = [rule(state="ESTABLISHED", target="ACCEPT")]
    assert evaluator(rules).evaluate(packet(state="NEW"))["action"] == "DROP"


def test_interface_suffix_wildcard_is_not_used():
    rules = [rule(iface="eth", target="ACCEPT")]
    assert evaluator(rules).evaluate(packet(iface="eth0"))["action"] == "DROP"


def test_reject_and_drop_are_counted():
    result = evaluator([rule(target="DROP")]).evaluate(packet())
    assert result["counts"]


def test_missing_default_policy_is_rejected():
    with pytest.raises(nf.RuleError):
        nf.NetfilterRuleEval([], default_policy=None)


def test_jump_depth_is_limited():
    rules = [rule(chain="INPUT", target="C1"), rule(chain="C1", target="C2"), rule(chain="C2", target="C3"), rule(chain="C3", target="C4"), rule(chain="C4", target="ACCEPT")]
    with pytest.raises(nf.RuleError):
        evaluator(rules, max_depth=2).evaluate(packet())


def test_chain_path_is_reported():
    rules = [rule(chain="INPUT", target="C1"), rule(chain="C1", target="ACCEPT")]
    assert evaluator(rules).evaluate(packet())["chains"] == ["INPUT", "C1"]


def test_final_action_is_reported():
    assert evaluator([rule(target="ACCEPT")]).evaluate(packet())["action"] == "ACCEPT"


def test_rule_counters_increment_on_deny():
    result = evaluator([rule(target="DROP")]).evaluate(packet())
    assert result["counts"]["DROP"] == 1


def test_result_is_repeatable():
    e = evaluator([rule(target="ACCEPT")])
    assert e.evaluate(packet()) == e.evaluate(packet())
