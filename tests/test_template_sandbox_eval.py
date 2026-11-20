import pytest

import template_sandbox_eval as ts


def tpl(expr):
    return "$" + "{" + expr + "}"


def box(**over):
    kwargs = {"allowed_fields": (), "undefined": "error", "max_length": 256, "max_depth": 8, "max_loops": 100}
    kwargs.update(over)
    return ts.TemplateSandbox(**kwargs)


def test_dunder_attribute_is_rejected():
    with pytest.raises(ts.TemplateError) as exc:
        box().render(tpl("user.__class__"), {"user": {}})
    assert exc.value.code == "forbidden_name"


def test_environment_variable_is_undefined_by_default():
    with pytest.raises(ts.TemplateError) as exc:
        box().render(tpl("env"), {})
    assert exc.value.code == "undefined_variable"
    assert exc.value.name == "env"


def test_profile_field_must_be_whitelisted():
    sb = box(allowed_fields=("user.name",))
    assert sb.render(tpl("user.name"), {"user": {"name": "Ada"}}) == "Ada"
    with pytest.raises(ts.TemplateError) as exc:
        sb.render(tpl("user.email"), {"user": {"email": "a@b.c"}})
    assert exc.value.code == "field_not_allowed"


def test_upper_and_lower_filters():
    assert box().render(tpl("name | upper"), {"name": "Ada"}) == "ADA"
    assert box().render(tpl("name | lower"), {"name": "Ada"}) == "ada"


def test_template_length_limit():
    with pytest.raises(ts.TemplateError) as exc:
        box(max_length=20).render("x" * 60, {})
    assert exc.value.code == "template_too_long"


def test_expression_depth_limit():
    with pytest.raises(ts.TemplateError) as exc:
        box(max_depth=2).render(tpl("((((1))))"), {})
    assert exc.value.code == "expression_too_deep"


def test_repeat_filter_respects_loop_limit():
    with pytest.raises(ts.TemplateError) as exc:
        box(max_loops=10).render(tpl("name | repeat(1000)"), {"name": "a"})
    assert exc.value.code == "loop_limit"


def test_undefined_can_render_empty_when_configured():
    assert box(undefined="empty").render(tpl("missing"), {}) == ""


def test_number_filter_uses_fixed_decimals():
    assert box().render(tpl("price | number(2)"), {"price": 1.2}) == "1.20"
    assert box().render(tpl("price | number(0)"), {"price": 3.6}) == "4"


def test_date_filter_only_accepts_iso_date():
    assert box().render(tpl("when | date"), {"when": "2024-01-02"}) == "2024-01-02"
    with pytest.raises(ts.TemplateError):
        box().render(tpl("when | date"), {"when": "01/02/2024"})


def test_output_is_html_escaped_by_default():
    assert box().render(tpl("name"), {"name": "<b>"}) == "&lt;b&gt;"


def test_raw_filter_disables_escaping():
    assert box().render(tpl("name | raw"), {"name": "<b>"}) == "<b>"


def test_nested_template_only_expands_one_level():
    assert box().render(tpl("a"), {"a": tpl("b"), "b": "x"}) == "x"
    with pytest.raises(ts.TemplateError) as exc:
        box().render(tpl("a"), {"a": tpl("b"), "b": tpl("c"), "c": "x"})
    assert exc.value.code == "nested_too_deep"


def test_syntax_error_reports_position():
    with pytest.raises(ts.TemplateError) as exc:
        box().render(tpl("1 +"), {})
    assert exc.value.code == "syntax_error"
    assert exc.value.name is not None


def test_render_is_repeatable_and_context_is_not_mutated():
    sb = box()
    context = {"name": "Ada", "price": 2}
    first = sb.render(tpl("name") + "/" + tpl("price | number(1)"), context)
    second = sb.render(tpl("name") + "/" + tpl("price | number(1)"), context)
    assert first == second
    assert context == {"name": "Ada", "price": 2}
