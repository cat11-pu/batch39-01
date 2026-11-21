import ipaddress


class RuleError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_TERMINAL_TARGETS = frozenset({"ACCEPT", "DROP", "REJECT"})
_CONTROL_TARGETS = frozenset({"RETURN"})
_KNOWN_TARGETS = _TERMINAL_TARGETS | _CONTROL_TARGETS


def _normalize_name(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise RuleError("invalid_" + field_name)
    return value.strip().casefold()


def _normalize_target(value):
    if not isinstance(value, str) or not value.strip():
        raise RuleError("invalid_target")
    target = value.strip()
    if target.upper() in _KNOWN_TARGETS:
        return target.upper()
    return target


def _normalize_network(value, field_name):
    if value is None:
        return None
    try:
        return ipaddress.ip_network(str(value).strip(), strict=False)
    except ValueError as exc:
        raise RuleError("invalid_" + field_name) from exc


def _normalize_port_range(value):
    if value is None:
        return None

    if isinstance(value, bool):
        raise RuleError("invalid_port_range")

    if isinstance(value, int):
        bounds = (value, value)
    elif isinstance(value, str):
        text = value.strip()
        if ":" in text:
            parts = text.split(":", 1)
        elif "-" in text:
            parts = text.split("-", 1)
        else:
            parts = [text]
        try:
            bounds = tuple(int(part.strip()) for part in parts)
        except ValueError as exc:
            raise RuleError("invalid_port_range") from exc
    elif isinstance(value, (tuple, list)):
        bounds = tuple(value)
    else:
        raise RuleError("invalid_port_range")

    if len(bounds) == 1:
        bounds = (bounds[0], bounds[0])
    if len(bounds) != 2 or any(isinstance(item, bool) or not isinstance(item, int) for item in bounds):
        raise RuleError("invalid_port_range")

    lower, upper = bounds
    if lower < 0 or upper < 0 or lower > 65535 or upper > 65535 or lower > upper:
        raise RuleError("invalid_port_range")
    return lower, upper


def _normalize_states(value):
    if value is None:
        return None
    if isinstance(value, str):
        states = [part.strip() for part in value.split(",")]
    elif isinstance(value, (tuple, list, set, frozenset)):
        states = list(value)
    else:
        raise RuleError("invalid_state")

    normalized = []
    for state in states:
        if not isinstance(state, str) or not state.strip():
            raise RuleError("invalid_state")
        normalized.append(state.strip().casefold())
    if not normalized:
        raise RuleError("invalid_state")
    return frozenset(normalized)


def _normalize_interfaces(value):
    if value is None:
        return None
    if isinstance(value, str):
        interfaces = [value]
    elif isinstance(value, (tuple, list, set, frozenset)):
        interfaces = list(value)
    else:
        raise RuleError("invalid_iface")

    normalized = []
    for interface in interfaces:
        if not isinstance(interface, str) or not interface.strip():
            raise RuleError("invalid_iface")
        normalized.append(interface.strip().casefold())
    if not normalized:
        raise RuleError("invalid_iface")
    return frozenset(normalized)


def _normalize_protocol(value):
    if value is None:
        return None
    return _normalize_name(value, "proto")


class NetfilterRuleEval:
    def __init__(self, rules, default_policy=None, max_depth=16):
        if default_policy is None or not isinstance(default_policy, str) or not default_policy.strip():
            raise RuleError("missing_default_policy")

        policy = default_policy.strip().upper()
        if policy not in _TERMINAL_TARGETS:
            raise RuleError("invalid_default_policy")

        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
            raise RuleError("invalid_max_depth")

        self.default_policy = policy
        self.max_depth = max_depth
        self.rules = []
        self._chain_rules = {}

        for index, source_rule in enumerate(rules):
            entry = self._prepare_rule(source_rule, index)
            self.rules.append(entry)
            self._chain_rules.setdefault(entry["chain"], []).append(entry)

        self._validate_jump_graph()

    def _validate_jump_graph(self):
        visiting = set()
        visited = set()

        def visit(chain):
            if chain in visiting:
                raise RuleError("jump_cycle")
            if chain in visited:
                return

            visiting.add(chain)
            for entry in self._chain_rules.get(chain, []):
                target = entry["target"]
                if target in _KNOWN_TARGETS:
                    continue
                if target in self._chain_rules:
                    visit(target)
                else:
                    raise RuleError("unknown_chain")
            visiting.remove(chain)
            visited.add(chain)

        for chain in self._chain_rules:
            visit(chain)

    @staticmethod
    def _prepare_rule(rule, index):
        if not isinstance(rule, dict):
            raise RuleError("invalid_rule")

        chain = rule.get("chain")
        if not isinstance(chain, str) or not chain.strip():
            raise RuleError("invalid_chain")

        return {
            "index": index,
            "rule": rule,
            "chain": chain.strip(),
            "target": _normalize_target(rule.get("target")),
            "src": _normalize_network(rule.get("src"), "src_network"),
            "dst": _normalize_network(rule.get("dst"), "dst_network"),
            "port": _normalize_port_range(rule.get("port")),
            "proto": _normalize_protocol(rule.get("proto")),
            "states": _normalize_states(rule.get("state")),
            "ifaces": _normalize_interfaces(rule.get("iface")),
        }

    @staticmethod
    def _address_matches(address, network):
        if address is None:
            return False
        try:
            parsed = ipaddress.ip_address(str(address).strip())
        except ValueError as exc:
            raise RuleError("invalid_packet_address") from exc
        return parsed.version == network.version and parsed in network

    @staticmethod
    def _port_matches(port, bounds):
        if port is None:
            return False
        if isinstance(port, bool):
            raise RuleError("invalid_packet_port")
        try:
            parsed = int(port)
        except (TypeError, ValueError) as exc:
            raise RuleError("invalid_packet_port") from exc
        return bounds[0] <= parsed <= bounds[1]

    @classmethod
    def _rule_matches(cls, entry, packet):
        if entry["src"] is not None and not cls._address_matches(packet.get("src"), entry["src"]):
            return False
        if entry["dst"] is not None and not cls._address_matches(packet.get("dst"), entry["dst"]):
            return False
        if entry["port"] is not None and not cls._port_matches(packet.get("port"), entry["port"]):
            return False

        if entry["proto"] is not None:
            protocol = packet.get("proto")
            if not isinstance(protocol, str) or protocol.strip().casefold() != entry["proto"]:
                return False

        if entry["states"] is not None:
            state = packet.get("state")
            if not isinstance(state, str) or state.strip().casefold() not in entry["states"]:
                return False

        if entry["ifaces"] is not None:
            interface = packet.get("iface")
            if not isinstance(interface, str) or interface.strip().casefold() not in entry["ifaces"]:
                return False

        return True

    def evaluate(self, packet):
        if not isinstance(packet, dict):
            raise RuleError("invalid_packet")

        start_chain = packet.get("chain", "INPUT")
        if not isinstance(start_chain, str) or not start_chain.strip():
            raise RuleError("invalid_chain")
        start_chain = start_chain.strip()

        counts = {}
        rule_counts = [0] * len(self.rules)
        chain_path = [start_chain]
        frames = [{"chain": start_chain, "index": 0}]
        active_chains = [start_chain]
        matched_rule = None
        matched_index = None

        while frames:
            frame = frames[-1]
            chain_rules = self._chain_rules.get(frame["chain"], [])

            if frame["index"] >= len(chain_rules):
                frames.pop()
                active_chains.pop()
                if not frames:
                    return {
                        "action": self.default_policy,
                        "matched_rule": matched_rule,
                        "matched_index": matched_index,
                        "chains": chain_path,
                        "counts": counts,
                        "rule_counts": rule_counts,
                    }
                continue

            entry = chain_rules[frame["index"]]
            frame["index"] += 1

            if not self._rule_matches(entry, packet):
                continue

            target = entry["target"]
            rule_counts[entry["index"]] += 1
            counts[target] = counts.get(target, 0) + 1
            matched_rule = entry["rule"]
            matched_index = entry["index"]

            if target in _TERMINAL_TARGETS:
                return {
                    "action": target,
                    "matched_rule": matched_rule,
                    "matched_index": matched_index,
                    "chains": chain_path,
                    "counts": counts,
                    "rule_counts": rule_counts,
                }

            if target in _CONTROL_TARGETS:
                frames.pop()
                active_chains.pop()
                if not frames:
                    return {
                        "action": self.default_policy,
                        "matched_rule": matched_rule,
                        "matched_index": matched_index,
                        "chains": chain_path,
                        "counts": counts,
                        "rule_counts": rule_counts,
                    }
                continue

            if target in active_chains:
                raise RuleError("jump_cycle")
            if len(frames) > self.max_depth:
                raise RuleError("jump_depth")
            if target not in self._chain_rules:
                raise RuleError("unknown_chain")

            frames.append({"chain": target, "index": 0})
            active_chains.append(target)
            chain_path.append(target)

        return {
            "action": self.default_policy,
            "matched_rule": matched_rule,
            "matched_index": matched_index,
            "chains": chain_path,
            "counts": counts,
            "rule_counts": rule_counts,
        }
