import copy
import re


class PamError(ValueError):
    def __init__(self, code, line=None, file=None):
        super().__init__(code)
        self.code = code
        self.line = line
        self.file = file


_STACK_TYPES = {"auth", "account", "password", "session"}
_KEYWORD_CONTROLS = {"required", "requisite", "sufficient", "optional", "include"}
_ACTIONS = {"ignore", "ok", "done", "bad", "die", "reset"}

_RETURN_CODES = {
    "success",
    "open_err",
    "symbol_err",
    "service_err",
    "system_err",
    "buf_err",
    "perm_denied",
    "auth_err",
    "cred_insufficient",
    "authinfo_unavail",
    "user_unknown",
    "maxtries",
    "max_tries",
    "new_authtok_reqd",
    "acct_expired",
    "session_err",
    "cred_unavail",
    "cred_expired",
    "cred_err",
    "no_module_data",
    "conv_err",
    "authtok_err",
    "authtok_recover_err",
    "authtok_lock_busy",
    "authtok_disable_aging",
    "try_again",
    "ignore",
    "abort",
    "authtok_expired",
    "module_unknown",
    "bad_item",
    "conv_again",
    "incomplete",
    "token_err",
}

_INTEGER_RE = re.compile(r"[+-]?\d+\Z")
_CONTINUATION_RE = re.compile(r"\\[ \t]*\Z")


class PamStackEval:
    def __init__(self, configs, modules, max_depth=8):
        self._configs = copy.deepcopy(dict(configs))
        self._modules = dict(modules)
        self.max_depth = int(max_depth)
        self._last_result = None

    def evaluate(self, stack_type, context=None):
        if stack_type not in _STACK_TYPES:
            raise PamError("unknown_stack")

        directives = self._expand_stack(stack_type)
        self._validate_jumps(directives)

        steps = []
        failed = False
        short_circuited = False
        index = 0
        executed = 0
        execution_limit = max(1000, len(directives) * 100)

        while index < len(directives):
            executed += 1
            if executed > execution_limit:
                directive = directives[index % len(directives)]
                raise PamError("jump_loop", directive["line"], directive["file"])

            directive = directives[index]
            module = directive["module"]
            callback = self._modules.get(module)
            if callback is None or not callable(callback):
                raise PamError("unknown_module", directive["line"], directive["file"])

            raw_return = callback(context)
            return_code = self._normalize_return(
                raw_return, directive["line"], directive["file"]
            )
            action = self._resolve_action(directive, return_code)

            steps.append(
                {
                    "module": module,
                    "args": list(directive["args"]),
                    "control": directive["control"],
                    "return_code": return_code,
                    "rc": return_code,
                    "line": directive["line"],
                    "file": directive["file"],
                }
            )

            if action[0] == "ignore":
                index += 1
            elif action[0] == "jump":
                index = self._jump_target(index, action[1])
            elif action[0] == "ok":
                index += 1
            elif action[0] == "done":
                short_circuited = True
                break
            elif action[0] == "bad":
                failed = True
                index += 1
            elif action[0] == "die":
                failed = True
                short_circuited = True
                break
            elif action[0] == "reset":
                failed = False
                index += 1

        result = {
            "result": "failure" if failed else "success",
            "short_circuited": short_circuited,
            "steps": steps,
        }
        self._last_result = copy.deepcopy(result)
        return result

    def snapshot(self):
        snapshot = {
            "configs": self._configs,
            "max_depth": self.max_depth,
        }
        if self._last_result is not None:
            snapshot["last_result"] = self._last_result
        return copy.deepcopy(snapshot)

    def _expand_stack(self, stack_type):
        if "main" not in self._configs:
            raise PamError("unknown_config")

        directives = []
        seen_modules = {}
        self._expand_file(
            "main",
            stack_type,
            depth=0,
            chain=("main",),
            directives=directives,
            seen_modules=seen_modules,
            include_line=None,
            include_file=None,
        )
        return directives

    def _expand_file(
        self,
        file_name,
        stack_type,
        depth,
        chain,
        directives,
        seen_modules,
        include_line,
        include_file,
    ):
        if file_name not in self._configs:
            raise PamError("include_not_found", include_line, include_file)

        text = self._configs[file_name]
        if not isinstance(text, str):
            raise PamError("invalid_config", include_line, include_file)

        for line_number, logical_line in self._logical_lines(text):
            content = self._strip_comment(logical_line)
            tokens = content.split()
            if not tokens:
                continue

            line_type = tokens[0].lower()
            if line_type not in _STACK_TYPES:
                raise PamError("unknown_type", line_number, file_name)
            if line_type != stack_type:
                continue

            if len(tokens) < 2:
                raise PamError("invalid_line", line_number, file_name)

            control, next_index = self._parse_control(
                tokens, 1, line_number, file_name
            )
            if control["kind"] == "include":
                if next_index >= len(tokens):
                    raise PamError("invalid_line", line_number, file_name)
                target = tokens[next_index]
                if target in chain:
                    raise PamError("include_cycle", line_number, file_name)
                if depth + 1 > self.max_depth:
                    raise PamError("include_depth", line_number, file_name)
                self._expand_file(
                    target,
                    stack_type,
                    depth + 1,
                    chain + (target,),
                    directives,
                    seen_modules,
                    line_number,
                    file_name,
                )
                continue

            if next_index >= len(tokens):
                raise PamError("invalid_line", line_number, file_name)

            module = tokens[next_index]
            args = tokens[next_index + 1 :]
            if module not in self._modules or not callable(self._modules[module]):
                raise PamError("unknown_module", line_number, file_name)
            signature = (control["raw"], module)
            if signature in seen_modules:
                raise PamError("duplicate_module", line_number, file_name)
            seen_modules[signature] = line_number

            directives.append(
                {
                    "module": module,
                    "args": args,
                    "control": control["raw"],
                    "kind": control["kind"],
                    "control_spec": control.get("spec"),
                    "line": line_number,
                    "file": file_name,
                }
            )

    def _parse_control(self, tokens, start, line, file_name):
        token = tokens[start]
        lowered = token.lower()

        if lowered in _KEYWORD_CONTROLS:
            kind = "include" if lowered == "include" else "keyword"
            return (
                {"kind": kind, "raw": lowered, "spec": None},
                start + 1,
            )

        if not token.startswith("["):
            return (
                {"kind": "keyword", "raw": "required", "spec": None},
                start,
            )

        pieces = [token]
        next_index = start + 1
        while "]" not in pieces[-1]:
            if next_index >= len(tokens):
                raise PamError("invalid_control", line, file_name)
            pieces.append(tokens[next_index])
            next_index += 1

        bracket = " ".join(pieces)
        close = bracket.find("]")
        if close < 0 or bracket[close + 1 :].strip():
            raise PamError("invalid_control", line, file_name)

        body = bracket[1:close].strip()
        if not body:
            raise PamError("invalid_control", line, file_name)

        rules = {}
        default_action = None
        for item in body.split():
            if "=" not in item:
                raise PamError("invalid_control", line, file_name)
            key, value = item.split("=", 1)
            key = key.strip().lower()
            value = value.strip().lower()
            if not key or not value:
                raise PamError("invalid_control", line, file_name)

            action = self._parse_action(value, line, file_name)
            if key == "default":
                default_action = action
                continue
            key = self._normalize_code(key)
            if key is None:
                raise PamError("unknown_control", line, file_name)
            rules[key] = action

        raw = bracket[: close + 1]
        return (
            {
                "kind": "bracket",
                "raw": raw,
                "spec": {"rules": rules, "default": default_action},
            },
            next_index,
        )

    def _parse_action(self, value, line, file_name):
        if _INTEGER_RE.fullmatch(value):
            return ("jump", int(value))
        if value in _ACTIONS:
            return (value, None)
        raise PamError("invalid_control", line, file_name)

    def _resolve_action(self, directive, return_code):
        if directive["kind"] == "keyword":
            control = directive["control"]
            if control == "required":
                if return_code == "ignore":
                    return ("ignore", None)
                return ("ok" if return_code == "success" else "bad", None)
            if control == "requisite":
                if return_code == "ignore":
                    return ("ignore", None)
                return ("ok" if return_code == "success" else "die", None)
            if control == "sufficient":
                if return_code == "success":
                    return ("done", None)
                return ("ignore", None)
            if control == "optional":
                return ("ignore", None)
            raise PamError(
                "invalid_control", directive["line"], directive["file"]
            )

        spec = directive["control_spec"]
        if return_code in spec["rules"]:
            return spec["rules"][return_code]
        if return_code == "ignore":
            return ("ignore", None)
        if spec["default"] is not None:
            return spec["default"]
        return ("bad", None)

    def _validate_jumps(self, directives):
        for index, directive in enumerate(directives):
            if directive["kind"] != "bracket":
                continue
            spec = directive["control_spec"]
            for action in spec["rules"].values():
                if action[0] == "jump":
                    self._check_jump(
                        index,
                        action[1],
                        len(directives),
                        directive["line"],
                        directive["file"],
                    )
            default_action = spec["default"]
            if default_action is not None and default_action[0] == "jump":
                self._check_jump(
                    index,
                    default_action[1],
                    len(directives),
                    directive["line"],
                    directive["file"],
                )

    def _check_jump(self, index, offset, length, line, file_name):
        target = self._jump_target(index, offset)
        if target < 0 or target >= length:
            raise PamError("jump_out_of_range", line, file_name)

    @staticmethod
    def _jump_target(index, offset):
        return index + offset + 1 if offset >= 0 else index + offset

    @staticmethod
    def _normalize_code(value):
        if not isinstance(value, str):
            return None
        code = value.strip().lower()
        if code.startswith("pam_"):
            code = code[4:]
        code = code.replace("-", "_")
        return code if code in _RETURN_CODES else None

    def _normalize_return(self, value, line, file_name):
        code = self._normalize_code(value)
        if code is None:
            raise PamError("unknown_return", line, file_name)
        return code

    @staticmethod
    def _logical_lines(text):
        physical = text.splitlines()
        index = 0
        while index < len(physical):
            line_number = index + 1
            logical = physical[index]
            while _CONTINUATION_RE.search(logical):
                logical = logical.rstrip()
                logical = logical[:-1].rstrip()
                index += 1
                if index >= len(physical):
                    break
                logical = logical + " " + physical[index].lstrip()
            yield line_number, logical
            index += 1

    @staticmethod
    def _strip_comment(line):
        in_bracket = False
        for index, char in enumerate(line):
            if char == "[":
                in_bracket = True
            elif char == "]":
                in_bracket = False
            elif (
                char == "#"
                and not in_bracket
                and (index == 0 or line[index - 1].isspace())
            ):
                return line[:index]
        return line
