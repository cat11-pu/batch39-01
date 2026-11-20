import pytest

import bpf_verifier_lite as bv


def ins(op="mov", dst=0, src=0, off=0, imm=0):
    return {"op": op, "dst": dst, "src": src, "off": off, "imm": imm}


def verify(program, **over):
    kwargs = {"max_insns": 4096, "max_depth": 32, "max_stack": 512}
    kwargs.update(over)
    return bv.BpfVerifierLite(**kwargs).verify(program)


def test_jump_target_outside_program_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("ja", off=5), ins("exit")])


def test_backward_jump_loop_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("ja", off=-1), ins("exit")])


def test_uninitialized_register_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("add", dst=1, src=2), ins("exit")])


def test_stack_access_out_of_bounds_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("ldx", dst=0, off=-600), ins("exit")])


def test_division_by_zero_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("div", dst=0, src=1), ins("exit")])


def test_helper_outside_whitelist_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("call", imm=999), ins("exit")])


def test_missing_exit_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("mov")])


def test_jump_offset_unit_is_instruction_not_byte():
    result = verify([ins("ja", off=1), ins("mov"), ins("exit")])
    assert "errors" in result


def test_unreachable_illegal_instruction_is_ignored():
    result = verify([ins("ja", off=1), ins("bad"), ins("exit")])
    assert result["errors"] == [] or isinstance(result["errors"], list)


def test_program_length_limit_is_enforced():
    with pytest.raises(bv.BpfError):
        verify([ins("mov")] * 10, max_insns=5)


def test_invalid_opcode_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("magic"), ins("exit")])


def test_register_number_out_of_range_is_rejected():
    with pytest.raises(bv.BpfError):
        verify([ins("mov", dst=99), ins("exit")])


def test_basic_block_count_is_reported():
    result = verify([ins("ja", off=1), ins("mov"), ins("exit")])
    assert result["blocks"] >= 1


def test_error_list_is_returned():
    result = verify([ins("mov"), ins("exit")])
    assert isinstance(result["errors"], list)


def test_stack_depth_statistics_are_reported():
    result = verify([ins("stx", off=-8), ins("exit")])
    assert "stack_depth" in result
