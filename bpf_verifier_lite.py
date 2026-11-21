class BpfError(ValueError):
    def __init__(self, code, index=None, errors=None, details=None):
        super().__init__(code)
        self.code = code
        self.index = index
        self.errors = list(errors) if errors is not None else [code]
        self.details = list(details) if details is not None else []


class BpfVerifierLite:
    REGISTER_COUNT = 11
    INITIAL_REGISTERS = frozenset((0, 10))
    INITIAL_CONSTANTS = {0: 0}
    OFF_MIN = -(1 << 15)
    OFF_MAX = (1 << 15) - 1
    IMM_MIN = -(1 << 31)
    IMM_MAX = (1 << 31) - 1

    HELPER_ARITY = {
        1: 2,
        2: 4,
        3: 2,
        4: 3,
        5: 0,
        6: 3,
        7: 0,
        8: 0,
        9: 5,
        10: 5,
        11: 5,
        12: 3,
        13: 4,
        14: 0,
        15: 0,
        16: 2,
        20: 5,
    }

    ALU_OPS = frozenset(
        ("add", "sub", "mul", "div", "mod", "and", "or", "xor", "lsh", "rsh", "arsh", "neg")
    )
    CONDITIONAL_JUMPS = frozenset(
        (
            "jeq",
            "jne",
            "jneq",
            "jgt",
            "jge",
            "jlt",
            "jle",
            "jset",
            "jsgt",
            "jsge",
            "jslt",
            "jsle",
            "jz",
            "jnz",
        )
    )
    UNCONDITIONAL_JUMPS = frozenset(("ja", "jmp", "goto"))
    LOAD_WIDTHS = {"": 8, "b": 1, "h": 2, "w": 4, "d": 8, "dw": 8, "q": 8, "64": 8}
    STORE_WIDTHS = {"": 8, "b": 1, "h": 2, "w": 4, "d": 8, "dw": 8, "q": 8, "64": 8}

    def __init__(self, max_insns=4096, max_depth=32, max_stack=512):
        self.max_insns = max_insns
        self.max_depth = max_depth
        self.max_stack = max_stack

    def verify(self, program):
        if not isinstance(program, (list, tuple)):
            raise BpfError("invalid_program")
        count = len(program)
        if count == 0:
            raise BpfError("empty_program")
        if count > self.max_insns:
            raise BpfError("program_too_long", self.max_insns)

        errors = []
        decoded = [None] * count
        reachable = set()
        successors = {}

        work = [0]
        while work:
            pc = work.pop()
            if pc in reachable or pc < 0 or pc >= count:
                continue
            reachable.add(pc)
            inst = self._decode(program[pc], pc, errors)
            decoded[pc] = inst
            if inst is None:
                continue

            edges = []
            kind = inst["kind"]
            if kind in ("ja", "jcc"):
                target = pc + 1 + inst["off"]
                if target < 0 or target >= count:
                    self._error(errors, "jump_target_out_of_range", pc)
                elif target <= pc:
                    self._error(errors, "backward_jump", pc)
                else:
                    edges.append((target, True))
                    work.append(target)
                if kind == "jcc" and pc + 1 < count:
                    edges.append((pc + 1, False))
                    work.append(pc + 1)
            elif kind != "exit" and pc + 1 < count:
                edges.append((pc + 1, False))
                work.append(pc + 1)
            successors[pc] = self._dedupe_edges(edges)

        if not self._raw_op(program[-1]) == "exit":
            self._error(errors, "missing_exit", count - 1)

        states = [None] * count
        states[0] = (set(self.INITIAL_REGISTERS), dict(self.INITIAL_CONSTANTS))
        stack_depth = 0
        jump_depths = [None] * count
        jump_depths[0] = 0

        for pc in range(count):
            if pc not in reachable:
                continue
            inst = decoded[pc]

            if jump_depths[pc] is not None:
                for target, is_jump in successors.get(pc, ()):
                    depth = jump_depths[pc] + (1 if is_jump else 0)
                    if depth > self.max_depth:
                        self._error(errors, "jump_depth_exceeded", pc)
                    if jump_depths[target] is None or depth > jump_depths[target]:
                        jump_depths[target] = depth

            state = states[pc]
            if inst is None or state is None:
                continue

            defined, constants = state
            next_state = self._execute(
                inst, defined, constants, stack_depth, errors
            )
            stack_depth = max(stack_depth, next_state[2])
            produced = (next_state[0], next_state[1])
            for target, _ in successors.get(pc, ()):
                states[target] = self._merge_states(states[target], produced)

        blocks = self._count_blocks(reachable, successors, decoded)

        if errors:
            details = list(errors)
            raise BpfError(
                details[0]["code"],
                details[0]["index"],
                errors=[item["code"] for item in details],
                details=details,
            )

        return {"errors": [], "blocks": blocks, "stack_depth": stack_depth}

    @staticmethod
    def _dedupe_edges(edges):
        merged = {}
        for target, is_jump in edges:
            merged[target] = merged.get(target, False) or is_jump
        return tuple((target, is_jump) for target, is_jump in merged.items())

    @staticmethod
    def _merge_states(old, new):
        if old is None:
            return (set(new[0]), dict(new[1]))
        old_defined, old_constants = old
        new_defined, new_constants = new
        merged_defined = old_defined & new_defined
        merged_constants = {
            reg: value
            for reg, value in old_constants.items()
            if reg in merged_defined
            and reg in new_constants
            and new_constants[reg] == value
        }
        return (merged_defined, merged_constants)

    def _execute(self, inst, defined, constants, stack_depth, errors):
        kind = inst["kind"]
        dst = inst["dst"]
        src = inst["src"]
        off = inst["off"]
        imm = inst["imm"]
        uses_immediate = imm != 0
        reads = []
        writes = []
        result = None

        if kind == "mov":
            if uses_immediate:
                writes.append(dst)
                result = imm
            else:
                reads.append(src)
                writes.append(dst)
                result = constants.get(src)
        elif kind in self.ALU_OPS:
            reads.append(dst)
            if kind != "neg":
                if uses_immediate:
                    rhs = imm
                    rhs_known = True
                else:
                    reads.append(src)
                    rhs = constants.get(src)
                    rhs_known = src in constants
                if kind in ("div", "mod") and rhs_known and rhs == 0:
                    self._error(errors, "division_by_zero", inst["index"])
                left = constants.get(dst)
                if dst in constants and (rhs_known or kind == "neg"):
                    try:
                        result = self._calculate(kind, left, rhs if kind != "neg" else None)
                    except (ArithmeticError, ValueError):
                        result = None
            else:
                if dst in constants:
                    result = -constants[dst]
            writes.append(dst)
        elif kind == "load":
            if inst.get("lddw"):
                writes.append(dst)
                result = imm
            else:
                width = inst["width"]
                self._check_stack(off, width, inst["index"], errors)
                stack_depth = max(stack_depth, -off)
                writes.append(dst)
        elif kind == "store":
            width = inst["width"]
            self._check_stack(off, width, inst["index"], errors)
            stack_depth = max(stack_depth, -off)
            if not uses_immediate:
                reads.append(src)
        elif kind == "ja":
            pass
        elif kind == "jcc":
            reads.append(dst)
            if not uses_immediate:
                reads.append(src)
        elif kind == "call":
            helper = imm
            arity = self.HELPER_ARITY.get(helper)
            if arity is None:
                self._error(errors, "invalid_helper", inst["index"])
            else:
                declared = inst.get("declared_nargs")
                if declared is not None and declared != arity:
                    self._error(errors, "helper_argument_count", inst["index"])
                reads.extend(range(1, arity + 1))
            writes.append(0)
            result = None

        for reg in reads:
            if reg not in defined:
                self._error(errors, "uninitialized_register", inst["index"])

        new_defined = set(defined)
        new_constants = dict(constants)
        for reg in writes:
            new_defined.add(reg)
            if result is None:
                new_constants.pop(reg, None)
            else:
                new_constants[reg] = result
        return (new_defined, new_constants, stack_depth)

    @staticmethod
    def _calculate(kind, left, right):
        if left is None:
            return None
        if kind == "add":
            return left + right
        if kind == "sub":
            return left - right
        if kind == "mul":
            return left * right
        if kind == "div":
            if right == 0:
                raise ZeroDivisionError
            return int(left / right)
        if kind == "mod":
            if right == 0:
                raise ZeroDivisionError
            quotient = int(left / right)
            return left - quotient * right
        if kind == "and":
            return left & right
        if kind == "or":
            return left | right
        if kind == "xor":
            return left ^ right
        if kind == "lsh":
            return left << (right & 63)
        if kind == "rsh":
            return (left & ((1 << 64) - 1)) >> (right & 63)
        if kind == "arsh":
            return left >> (right & 63)
        if kind == "neg":
            return -left
        return None

    def _check_stack(self, off, width, index, errors):
        if off + width > 0 or off < -self.max_stack:
            self._error(errors, "stack_out_of_bounds", index)

    def _decode(self, raw, index, errors):
        if not isinstance(raw, dict):
            self._error(errors, "invalid_instruction", index)
            return None
        op = raw.get("op")
        if not isinstance(op, str) or not op.strip():
            self._error(errors, "invalid_opcode", index)
            return None

        raw_dst = raw.get("dst", 0)
        raw_src = raw.get("src", 0)
        raw_off = raw.get("off", 0)
        raw_imm = raw.get("imm", 0)

        dst_ok = self._valid_register(raw_dst)
        src_ok = self._valid_register(raw_src)
        imm_ok = self._valid_int(raw_imm, self.IMM_MIN, self.IMM_MAX)
        off_ok = self._valid_int(raw_off, self.OFF_MIN, self.OFF_MAX)

        if not dst_ok or not src_ok:
            self._error(errors, "register_out_of_range", index)
        if not imm_ok:
            self._error(errors, "immediate_out_of_range", index)
        if not off_ok:
            self._error(errors, "offset_out_of_range", index)

        classification = self._classify(op)
        if classification is None:
            self._error(errors, "invalid_opcode", index)
            return None
        kind, width = classification
        if kind in ("load", "store"):
            declared_width = raw.get("size", raw.get("width"))
            if declared_width in (1, 2, 4, 8):
                width = declared_width
        inst = {
            "kind": kind,
            "width": width,
            "dst": raw_dst if dst_ok else 0,
            "src": raw_src if src_ok else 0,
            "off": raw_off if off_ok else 0,
            "imm": raw_imm if imm_ok else 0,
            "index": index,
            "lddw": kind == "load" and self._raw_op(raw) == "lddw",
        }
        declared = self._declared_arg_count(raw)
        if declared is not None:
            inst["declared_nargs"] = declared
        return inst

    @staticmethod
    def _declared_arg_count(raw):
        if "nargs" in raw:
            return raw["nargs"]
        if "argc" in raw:
            return raw["argc"]
        if "args" in raw:
            try:
                return len(raw["args"])
            except TypeError:
                return None
        return None

    @staticmethod
    def _valid_register(value):
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < BpfVerifierLite.REGISTER_COUNT

    @staticmethod
    def _valid_int(value, minimum, maximum):
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and minimum <= value <= maximum
        )

    def _classify(self, op):
        name = op.strip().lower().replace("_", "")
        if name == "exit":
            return ("exit", None)
        if name == "nop":
            return ("nop", None)
        if name in self.UNCONDITIONAL_JUMPS:
            return ("ja", None)
        if name in ("call", "helper"):
            return ("call", None)
        if name in self.CONDITIONAL_JUMPS:
            return ("jcc", None)

        for suffix in ("64", "32"):
            if name.endswith(suffix):
                stem = name[: -len(suffix)]
                if stem in self.UNCONDITIONAL_JUMPS:
                    return ("ja", None)
                if stem in self.CONDITIONAL_JUMPS:
                    return ("jcc", None)
                if stem in self.ALU_OPS or stem == "mov":
                    name = stem
                    break

        if name == "mov":
            return ("mov", None)
        if name in self.ALU_OPS:
            return (name, None)
        if name == "lddw":
            return ("load", 8)

        for prefix, kind, widths in (
            ("ldx", "load", self.LOAD_WIDTHS),
            ("ld", "load", self.LOAD_WIDTHS),
            ("stx", "store", self.STORE_WIDTHS),
            ("st", "store", self.STORE_WIDTHS),
        ):
            if name.startswith(prefix):
                suffix = name[len(prefix):]
                if suffix in widths:
                    return (kind, widths[suffix])
        return None

    def _count_blocks(self, reachable, successors, decoded):
        leaders = {0} if 0 in reachable else set()
        for pc in reachable:
            inst = decoded[pc]
            if inst is None:
                continue
            for target, _ in successors.get(pc, ()):
                leaders.add(target)
            if inst["kind"] in ("ja", "jcc") and pc + 1 in reachable:
                leaders.add(pc + 1)
        return len(leaders & reachable)

    @staticmethod
    def _raw_op(raw):
        if not isinstance(raw, dict):
            return None
        op = raw.get("op")
        if not isinstance(op, str):
            return None
        return op.strip().lower().replace("_", "")

    @staticmethod
    def _error(errors, code, index):
        for item in errors:
            if item["code"] == code and item["index"] == index:
                return
        errors.append({"code": code, "index": index})
