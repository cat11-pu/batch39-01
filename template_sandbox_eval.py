import ast
import html
import io
import math
import operator
import tokenize
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import ModuleType


class TemplateError(ValueError):
    def __init__(self, code, name=None):
        super().__init__(code)
        self.code = code
        self.name = name


class _Value:
    __slots__ = ("value", "raw")

    def __init__(self, value, raw=False):
        self.value = value
        self.raw = raw


class _RenderState:
    __slots__ = ("loops_left",)

    def __init__(self, max_loops):
        self.loops_left = max_loops


class TemplateSandbox:
    _FILTERS = {
        "capitalize",
        "date",
        "default",
        "length",
        "lower",
        "number",
        "raw",
        "repeat",
        "strip",
        "title",
        "trim",
        "upper",
    }

    _BIN_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    _COMPARE_OPS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.In: lambda left, right: left in right,
        ast.NotIn: lambda left, right: left not in right,
        ast.Is: operator.is_,
        ast.IsNot: operator.is_not,
    }

    def __init__(self, allowed_fields=(), undefined="error", max_length=256, max_depth=8, max_loops=100):
        if undefined not in ("error", "empty"):
            raise ValueError("undefined must be 'error' or 'empty'")
        if max_length is not None and (not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 0):
            raise ValueError("max_length must be a non-negative integer or None")
        if max_depth is not None and (not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 1):
            raise ValueError("max_depth must be a positive integer or None")
        if not isinstance(max_loops, int) or isinstance(max_loops, bool) or max_loops < 0:
            raise ValueError("max_loops must be a non-negative integer")

        if allowed_fields is None:
            allowed_fields = ()
        elif isinstance(allowed_fields, str):
            allowed_fields = (allowed_fields,)
        self.allowed_fields = frozenset(str(field) for field in allowed_fields)
        self.undefined = undefined
        self.max_length = max_length
        self.max_depth = max_depth
        self.max_loops = max_loops

    def render(self, template, context):
        if not isinstance(template, str):
            raise TemplateError("invalid_template")
        if self.max_length is not None and len(template) > self.max_length:
            raise TemplateError("template_too_long")
        if context is None:
            context = {}
        if not isinstance(context, Mapping):
            raise TypeError("context must be a mapping")

        state = _RenderState(self.max_loops)
        return self._render_template(template, context, 0, state)

    def _render_template(self, template, context, level, state):
        parts = self._parse_template(template)
        output = []
        for kind, value, position in parts:
            if kind == "text":
                output.append(value)
                continue

            rendered = self._render_expression(value, context, position, state)
            if rendered.raw:
                text_value = self._to_text(rendered.value)
                if "${" in text_value:
                    output.append(self._expand_nested(text_value, context, level, state, position))
                else:
                    output.append(text_value)
            else:
                text_value = self._to_text(rendered.value)
                if "${" in text_value:
                    output.append(self._expand_nested(text_value, context, level, state, position))
                else:
                    output.append(html.escape(text_value, quote=True))
        return "".join(output)

    def _expand_nested(self, text_value, context, level, state, position):
        if level >= 1:
            raise TemplateError("nested_too_deep", name=f"offset {position}")
        return self._render_template(text_value, context, level + 1, state)

    def _parse_template(self, template):
        parts = []
        text_start = 0
        index = 0
        length = len(template)

        while index < length:
            if not template.startswith("${", index):
                index += 1
                continue

            if index > text_start:
                parts.append(("text", template[text_start:index], text_start))

            expression_start = index + 2
            cursor = expression_start
            quote = None
            escaped = False
            while cursor < length:
                char = template[cursor]
                if quote is not None:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = None
                elif char in ("'", '"'):
                    quote = char
                elif char == "}":
                    break
                cursor += 1

            if cursor >= length or template[cursor] != "}":
                raise TemplateError("syntax_error", name=f"unterminated expression at offset {index}")
            if quote is not None:
                raise TemplateError("syntax_error", name=f"unterminated string at offset {expression_start}")

            expression = template[expression_start:cursor]
            if not expression.strip():
                raise TemplateError("syntax_error", name=f"empty expression at offset {index}")
            parts.append(("expr", expression, index))
            index = cursor + 1
            text_start = index

        if text_start < length:
            parts.append(("text", template[text_start:], text_start))
        return parts

    def _render_expression(self, expression, context, position, state):
        self._check_group_depth(expression)
        segments = self._split_pipeline(expression)
        base_node = self._parse_node(segments[0])
        self._check_forbidden_names(base_node)
        self._check_ast_depth(base_node)
        value = self._eval(base_node, context, state, final=True)

        for segment in segments[1:]:
            if not segment.strip():
                raise TemplateError("syntax_error", name=f"empty filter at offset {position}")
            filter_name, argument_nodes = self._parse_filter(segment)
            if filter_name.startswith("_"):
                raise TemplateError("forbidden_name", name=filter_name)
            if filter_name not in self._FILTERS:
                raise TemplateError("unknown_filter", name=filter_name)

            arguments = []
            for argument_node in argument_nodes:
                self._check_ast_depth(argument_node)
                arguments.append(self._eval(argument_node, context, state, final=True).value)
            value = self._apply_filter(filter_name, value, arguments, state)

        self._validate_output_value(value.value)
        return value

    def _parse_node(self, expression):
        try:
            return ast.parse(expression.strip(), mode="eval").body
        except SyntaxError as exc:
            location = f"line {exc.lineno}, column {exc.offset}"
            raise TemplateError("syntax_error", name=location) from None
        except (ValueError, TypeError) as exc:
            raise TemplateError("syntax_error", name=str(exc)) from None

    def _parse_filter(self, segment):
        node = self._parse_node(segment)
        self._check_forbidden_names(node)
        self._check_ast_depth(node)
        if isinstance(node, ast.Name):
            return node.id, []
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise TemplateError("forbidden_call")
            if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
                raise TemplateError("filter_argument_error")
            return node.func.id, node.args
        raise TemplateError("syntax_error", name=f"invalid filter at offset {segment!r}")

    def _check_forbidden_names(self, node):
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id.startswith("_"):
                raise TemplateError("forbidden_name", name=child.id)
            if isinstance(child, ast.Attribute) and child.attr.startswith("_"):
                raise TemplateError("forbidden_name", name=child.attr)
            if isinstance(child, ast.keyword) and child.arg and child.arg.startswith("_"):
                raise TemplateError("forbidden_name", name=child.arg)

    def _check_group_depth(self, expression):
        if self.max_depth is None:
            return
        depth = 0
        max_seen = 0
        try:
            tokens = tokenize.generate_tokens(io.StringIO(expression).readline)
            for token in tokens:
                if token.type != tokenize.OP:
                    continue
                if token.string in "([{":
                    depth += 1
                    max_seen = max(max_seen, depth)
                elif token.string in ")]}":
                    depth = max(0, depth - 1)
        except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
            raise TemplateError("syntax_error", name=str(exc)) from None
        if max_seen > self.max_depth:
            raise TemplateError("expression_too_deep")

    def _check_ast_depth(self, node):
        if self.max_depth is None:
            return
        if self._node_depth(node) > self.max_depth:
            raise TemplateError("expression_too_deep")

    def _node_depth(self, node):
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            return 1 + max(
                self._binop_operand_depth(node.left, op_type),
                self._binop_operand_depth(node.right, op_type),
            )
        children = list(ast.iter_child_nodes(node))
        if not children:
            return 1
        return 1 + max(self._node_depth(child) for child in children)

    def _binop_operand_depth(self, node, op_type):
        if isinstance(node, ast.BinOp) and type(node.op) is op_type:
            return max(
                self._binop_operand_depth(node.left, op_type),
                self._binop_operand_depth(node.right, op_type),
            )
        return self._node_depth(node)

    def _split_pipeline(self, expression):
        segments = []
        start = 0
        depth = 0
        quote = None
        escaped = False

        for index, char in enumerate(expression):
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in ("'", '"'):
                quote = char
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                depth = max(0, depth - 1)
            elif char == "|" and depth == 0:
                segment = expression[start:index]
                if not segment.strip():
                    raise TemplateError("syntax_error", name="empty expression")
                segments.append(segment)
                start = index + 1

        if quote is not None:
            raise TemplateError("syntax_error", name="unterminated string")
        segment = expression[start:]
        if not segment.strip():
            raise TemplateError("syntax_error", name="empty filter")
        segments.append(segment)
        return segments

    def _eval(self, node, context, state, final=False):
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, complex):
                raise TemplateError("unsupported_constant")
            if isinstance(value, float) and not math.isfinite(value):
                raise TemplateError("unsupported_constant")
            if value is not Ellipsis and not isinstance(value, (str, int, float, bool, type(None))):
                raise TemplateError("unsupported_constant")
            return _Value(value)

        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise TemplateError("forbidden_name", name=node.id)
            if node.id not in context:
                return self._undefined(node.id)
            value = context[node.id]
            self._reject_dangerous_value(value, node.id)
            return _Value(value)

        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise TemplateError("forbidden_name", name=node.attr)
            path = self._attribute_path(node)
            if path is None:
                raise TemplateError("field_not_allowed", name=node.attr)
            for component in path.split("."):
                if component.startswith("_"):
                    raise TemplateError("forbidden_name", name=component)

            base = self._eval(node.value, context, state, final=False).value
            if not self._field_allowed(path, final):
                raise TemplateError("field_not_allowed", name=path)

            value = self._read_field(base, node.attr, path)
            return _Value(value)

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self._BIN_OPS:
                raise TemplateError("unsupported_operator")
            left = self._eval(node.left, context, state, final=False).value
            right = self._eval(node.right, context, state, final=False).value
            return _Value(self._apply_bin_op(op_type, left, right, state))

        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, context, state, final=False).value
            if isinstance(node.op, ast.USub):
                self._require_number(operand)
                return _Value(-operand)
            if isinstance(node.op, ast.UAdd):
                self._require_number(operand)
                return _Value(+operand)
            if isinstance(node.op, ast.Not):
                return _Value(not operand)
            raise TemplateError("unsupported_operator")

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result = _Value(True)
                for value_node in node.values:
                    result = self._eval(value_node, context, state, final=False)
                    if not result.value:
                        return result
                return result
            if isinstance(node.op, ast.Or):
                result = _Value(False)
                for value_node in node.values:
                    result = self._eval(value_node, context, state, final=False)
                    if result.value:
                        return result
                return result
            raise TemplateError("unsupported_operator")

        if isinstance(node, ast.Compare):
            left = self._eval(node.left, context, state, final=False).value
            for op, comparator in zip(node.ops, node.comparators):
                op_type = type(op)
                if op_type not in self._COMPARE_OPS:
                    raise TemplateError("unsupported_operator")
                right = self._eval(comparator, context, state, final=False).value
                try:
                    if not self._COMPARE_OPS[op_type](left, right):
                        return _Value(False)
                except Exception:
                    raise TemplateError("evaluation_error") from None
                left = right
            return _Value(True)

        if isinstance(node, ast.Call):
            raise TemplateError("forbidden_call")

        raise TemplateError("unsupported_expression", name=type(node).__name__)

    def _attribute_path(self, node):
        attributes = []
        current = node
        while isinstance(current, ast.Attribute):
            attributes.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        attributes.append(current.id)
        return ".".join(reversed(attributes))

    def _field_allowed(self, path, final):
        if path in self.allowed_fields:
            return True
        if final:
            return False
        prefix = path + "."
        return any(field.startswith(prefix) for field in self.allowed_fields)

    def _read_field(self, base, attribute, path):
        if isinstance(base, Mapping):
            if attribute in base:
                value = base[attribute]
            else:
                return self._undefined(path).value
        elif isinstance(base, (str, bytes, int, float, bool, type(None), list, tuple, set, dict)):
            raise TemplateError("field_not_allowed", name=path)
        else:
            try:
                value = getattr(base, attribute)
            except AttributeError:
                return self._undefined(path).value
            except Exception:
                raise TemplateError("evaluation_error", name=path) from None
        self._reject_dangerous_value(value, path)
        return value

    def _reject_dangerous_value(self, value, name):
        if isinstance(value, type) or callable(value):
            raise TemplateError("forbidden_name", name=name)
        if isinstance(value, ModuleType):
            raise TemplateError("forbidden_name", name=name)

    def _undefined(self, name):
        if self.undefined == "empty":
            return _Value("")
        raise TemplateError("undefined_variable", name=name)

    def _require_number(self, value):
        if not isinstance(value, (int, float)) or isinstance(value, complex):
            raise TemplateError("evaluation_error")

    def _apply_bin_op(self, op_type, left, right, state):
        if op_type is ast.Add:
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            self._require_number(left)
            self._require_number(right)
            result = left + right
        elif op_type is ast.Mult:
            if isinstance(left, str) and isinstance(right, int) and not isinstance(right, bool):
                return self._repeat_text(left, right, state)
            if isinstance(right, str) and isinstance(left, int) and not isinstance(left, bool):
                return self._repeat_text(right, left, state)
            self._require_number(left)
            self._require_number(right)
            result = left * right
        elif op_type is ast.Pow:
            self._require_number(left)
            self._require_number(right)
            if not isinstance(right, int) or isinstance(right, bool) or abs(right) > 1000:
                raise TemplateError("evaluation_error")
            try:
                result = left ** right
            except (ArithmeticError, ValueError):
                raise TemplateError("evaluation_error") from None
        elif op_type is ast.Mod:
            self._require_number(left)
            self._require_number(right)
            try:
                result = left % right
            except (ArithmeticError, ValueError):
                raise TemplateError("evaluation_error") from None
        else:
            self._require_number(left)
            self._require_number(right)
            try:
                result = self._BIN_OPS[op_type](left, right)
            except (ArithmeticError, ValueError):
                raise TemplateError("evaluation_error") from None
        return self._check_numeric_result(result)

    def _check_numeric_result(self, result):
        if isinstance(result, complex):
            raise TemplateError("unsupported_value")
        if isinstance(result, float) and not math.isfinite(result):
            raise TemplateError("unsupported_value")
        if isinstance(result, int) and result.bit_length() > 14_000:
            raise TemplateError("output_too_long")
        return result

    def _repeat_text(self, value, count, state):
        if not isinstance(count, int) or isinstance(count, bool):
            raise TemplateError("loop_limit")
        if count < 0:
            count = 0
        if count > state.loops_left:
            raise TemplateError("loop_limit")
        state.loops_left -= count
        result = value * count
        if len(result) > 1_000_000:
            raise TemplateError("output_too_long")
        return result

    def _apply_filter(self, name, value, arguments, state):
        current = value.value
        raw = value.raw

        if name == "upper":
            self._expect_args(name, arguments, 0)
            current = self._to_text(current).upper()
        elif name == "lower":
            self._expect_args(name, arguments, 0)
            current = self._to_text(current).lower()
        elif name == "capitalize":
            self._expect_args(name, arguments, 0)
            current = self._to_text(current).capitalize()
        elif name == "title":
            self._expect_args(name, arguments, 0)
            current = self._to_text(current).title()
        elif name in ("strip", "trim"):
            self._expect_args(name, arguments, 0)
            current = self._to_text(current).strip()
        elif name in ("length", "len"):
            self._expect_args(name, arguments, 0)
            current = len(current) if hasattr(current, "__len__") else len(self._to_text(current))
        elif name == "default":
            self._expect_args(name, arguments, 1)
            if current is None or current == "":
                current = arguments[0]
        elif name == "number":
            self._expect_args(name, arguments, 0, maximum=1)
            digits = arguments[0] if arguments else 2
            current = self._format_number(current, digits)
        elif name == "date":
            self._expect_args(name, arguments, 0)
            current = self._format_date(current)
        elif name == "repeat":
            self._expect_args(name, arguments, 1)
            count = arguments[0]
            if not isinstance(count, int) or isinstance(count, bool):
                raise TemplateError("loop_limit")
            current = self._repeat_text(self._to_text(current), count, state)
        elif name == "raw":
            self._expect_args(name, arguments, 0)
            raw = True
        else:
            raise TemplateError("unknown_filter", name=name)

        return _Value(current, raw=raw)

    def _expect_args(self, name, arguments, minimum, maximum=None):
        if maximum is None:
            maximum = minimum
        if len(arguments) < minimum or len(arguments) > maximum:
            raise TemplateError("filter_argument_error", name=name)

    def _format_number(self, value, digits):
        if not isinstance(digits, int) or isinstance(digits, bool) or digits < 0 or digits > 1000:
            raise TemplateError("filter_argument_error", name="number")
        if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
            raise TemplateError("invalid_number")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError, OverflowError):
            raise TemplateError("invalid_number") from None
        if not number.is_finite():
            raise TemplateError("invalid_number")
        if number != 0 and abs(number.adjusted()) > 100_000:
            raise TemplateError("output_too_long")
        result = format(number, f".{digits}f")
        if len(result) > 1_000_000:
            raise TemplateError("output_too_long")
        return result

    def _format_date(self, value):
        if not isinstance(value, str):
            raise TemplateError("invalid_date")
        if value != value.strip() or " " in value:
            raise TemplateError("invalid_date")
        try:
            date.fromisoformat(value)
        except ValueError:
            try:
                datetime.fromisoformat(value)
            except ValueError:
                raise TemplateError("invalid_date") from None
        return value

    def _to_text(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, int):
            try:
                return str(value)
            except (ValueError, MemoryError):
                raise TemplateError("output_too_long") from None
        if isinstance(value, float):
            if not math.isfinite(value):
                raise TemplateError("unsupported_value")
            try:
                return format(Decimal(str(value)), "f")
            except (InvalidOperation, ValueError, OverflowError):
                raise TemplateError("unsupported_value") from None
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise TemplateError("unsupported_value")
            if value != 0 and abs(value.adjusted()) > 100_000:
                raise TemplateError("output_too_long")
            return format(value, "f")
        if isinstance(value, (Mapping, list, tuple, set, frozenset)):
            raise TemplateError("unsupported_value")
        self._reject_dangerous_value(value, type(value).__name__)
        raise TemplateError("unsupported_value")

    def _validate_output_value(self, value):
        if isinstance(value, (Mapping, list, tuple, set, frozenset)):
            raise TemplateError("unsupported_value")
        self._reject_dangerous_value(value, type(value).__name__)
