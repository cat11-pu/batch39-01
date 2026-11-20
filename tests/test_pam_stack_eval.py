import pytest

import pam_stack_eval as pe


def result(code):
    return lambda ctx: code


def evaluator(rules, modules=None, **over):
    mods = {"ok": result("success"), "bad": result("auth_err")}
    mods.update(modules or {})
    kwargs = {"configs": {"main": rules}, "modules": mods, "max_depth": 8}
    kwargs.update(over)
    return pe.PamStackEval(**kwargs)


def test_required_failure_collects_but_fails():
    e = evaluator("auth required bad\nauth required ok")
    r = e.evaluate("auth")
    assert r["result"] == "failure"
    assert len(r["steps"]) == 2


def test_requisite_failure_stops_stack():
    e = evaluator("auth requisite bad\nauth required ok")
    r = e.evaluate("auth")
    assert r["result"] == "failure"
    assert len(r["steps"]) == 1


def test_sufficient_success_short_circuits():
    e = evaluator("auth sufficient ok\nauth required bad")
    r = e.evaluate("auth")
    assert r["result"] == "success"
    assert r["short_circuited"] is True


def test_optional_failure_is_ignored():
    e = evaluator("auth optional bad\nauth required ok")
    assert e.evaluate("auth")["result"] == "success"


def test_bracket_jump_control_is_applied():
    e = evaluator("auth [success=1 default=ignore] bad\nauth required ok\nauth required bad")
    r = e.evaluate("auth")
    assert r["result"] == "failure"


def test_jump_out_of_range_is_rejected():
    with pytest.raises(pe.PamError) as exc:
        evaluator("auth [success=99] ok").evaluate("auth")
    assert exc.value.code == "jump_out_of_range"


def test_include_cycle_is_rejected():
    configs = {"main": "auth include other", "other": "auth include main"}
    e = pe.PamStackEval(configs, {"ok": result("success")})
    with pytest.raises(pe.PamError) as exc:
        e.evaluate("auth")
    assert exc.value.code == "include_cycle"


def test_include_depth_is_limited():
    configs = {"main": "auth include c1", "c1": "auth include c2", "c2": "auth include c3", "c3": "auth include c4"}
    e = pe.PamStackEval(configs, {"ok": result("success")}, max_depth=2)
    with pytest.raises(pe.PamError) as exc:
        e.evaluate("auth")
    assert exc.value.code == "include_depth"


def test_line_continuation_merges_arguments():
    e = evaluator("auth required ok \\\n arg_one")
    assert e.evaluate("auth")["steps"][0]["args"] == ["arg_one"]


def test_comment_brackets_are_ignored():
    e = evaluator("# auth [success=1]\nauth required ok")
    assert e.evaluate("auth")["result"] == "success"


def test_duplicate_module_is_rejected():
    with pytest.raises(pe.PamError) as exc:
        evaluator("auth required ok\nauth required ok").evaluate("auth")
    assert exc.value.code == "duplicate_module"


def test_four_stack_types_are_independent():
    rules = "auth required ok\naccount required bad\npassword required ok\nsession required ok"
    e = evaluator(rules)
    assert e.evaluate("auth")["result"] == "success"
    assert e.evaluate("account")["result"] == "failure"


def test_unknown_module_is_reported():
    with pytest.raises(pe.PamError) as exc:
        evaluator("auth required missing").evaluate("auth")
    assert exc.value.code == "unknown_module"


def test_unknown_return_code_is_reported():
    with pytest.raises(pe.PamError) as exc:
        evaluator("auth required weird", {"weird": result("bogus")}).evaluate("auth")
    assert exc.value.code == "unknown_return"


def test_snapshot_reports_lines_and_is_detached():
    e = evaluator("auth required ok")
    snap = e.snapshot()
    snap["configs"].clear()
    assert e.snapshot()["configs"]
    assert e.evaluate("auth")["steps"][0]["line"] == 1
