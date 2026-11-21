class CapError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_CAPABILITIES = [
    "cap_chown",
    "cap_dac_override",
    "cap_dac_read_search",
    "cap_fowner",
    "cap_fsetid",
    "cap_kill",
    "cap_setgid",
    "cap_setuid",
    "cap_setpcap",
    "cap_linux_immutable",
    "cap_net_bind_service",
    "cap_net_broadcast",
    "cap_net_admin",
    "cap_net_raw",
    "cap_ipc_lock",
    "cap_ipc_owner",
    "cap_sys_module",
    "cap_sys_rawio",
    "cap_sys_chroot",
    "cap_sys_ptrace",
    "cap_sys_pacct",
    "cap_sys_admin",
    "cap_sys_boot",
    "cap_sys_nice",
    "cap_sys_resource",
    "cap_sys_time",
    "cap_sys_tty_config",
    "cap_mknod",
    "cap_lease",
    "cap_audit_write",
    "cap_audit_control",
    "cap_setfcap",
    "cap_mac_override",
    "cap_mac_admin",
    "cap_syslog",
    "cap_wake_alarm",
    "cap_block_suspend",
    "cap_audit_read",
    "cap_perfmon",
    "cap_bpf",
    "cap_checkpoint_restore",
]

_CAP_NAMES = frozenset(_CAPABILITIES)
_MAX_CAP_NUMBER = 63
_PROCESS_FLAG_TARGETS = {"p": "permitted", "e": "effective", "i": "inheritable"}
_FILE_FLAG_TARGETS = {
    "p": ("file_permitted", "file_permitted_caps", "permitted"),
    "e": ("file_effective", "file_effective_caps", "effective"),
    "i": ("file_inheritable", "file_inheritable_caps", "inheritable"),
}


def _caps_of(source, key):
    value = (source or {}).get(key)
    if value is True:
        return set(_CAPABILITIES)
    if isinstance(value, (set, frozenset, list, tuple)):
        return set(value)
    return set()


class CapabilitySetParse:
    def __init__(self):
        self._by_number = {index: name for index, name in enumerate(_CAPABILITIES)}

    def parse(self, text):
        result = {
            "all": False,
            "empty": False,
            "missing": False,
            "permitted": set(),
            "effective": set(),
            "inheritable": set(),
            "bounding": set(),
            "bounding_dropped": set(),
            "ambient": set(),
            "file_permitted": False,
            "file_effective": False,
            "file_inheritable": False,
            "file_permitted_caps": set(),
            "file_effective_caps": set(),
            "file_inheritable_caps": set(),
            "warnings": [],
        }
        if text is None:
            result["missing"] = True
            return result
        text = text.strip()
        if not text:
            result["empty"] = True
            return result
        seen = set()
        for raw_item in text.split(","):
            item = raw_item.strip().lower()
            if not item:
                continue
            self._apply_item(item, result, seen)
        return result

    def _apply_item(self, item, result, seen):
        if item == "none":
            result["empty"] = True
            return
        if item == "all":
            if result["all"]:
                result["warnings"].append("duplicate-all-keyword")
            result["all"] = True
            result["permitted"] = set(_CAPABILITIES)
            return
        if "=" in item:
            name, flags = item.split("=", 1)
            self._apply_file_flags(self._resolve_name(name), flags, result, seen)
            return
        if "+" in item:
            name, flags = item.split("+", 1)
            self._apply_process_flags(self._resolve_name(name), flags, result, seen)
            return
        if "-" in item:
            name, suffix = item.split("-", 1)
            if suffix != "bounding":
                raise CapError("unknown-set-modifier")
            self._drop_from_bounding(self._resolve_name(name), result)
            return
        self._add_to_set(result, "permitted", self._resolve_name(item), seen)

    def _resolve_name(self, token):
        token = token.strip()
        if not token:
            raise CapError("empty-capability-token")
        if token.isdigit():
            number = int(token)
            if number < 0 or number > _MAX_CAP_NUMBER:
                raise CapError("capability-number-out-of-range")
            return self._by_number.get(number, "cap_%d" % number)
        name = token if token.startswith("cap_") else "cap_" + token
        if name not in _CAP_NAMES:
            raise CapError("unknown-capability")
        return name

    def _add_to_set(self, result, target, name, seen):
        if name in result["bounding_dropped"]:
            raise CapError("bounding-set-can-only-shrink")
        if result["all"] and target == "permitted":
            result["warnings"].append("all-keyword-covers-%s" % name)
            return
        key = (target, name)
        if key in seen:
            result["warnings"].append("duplicate-capability-%s" % name)
        seen.add(key)
        current = result[target]
        if current is True:
            return
        current.add(name)

    def _apply_process_flags(self, name, flags, result, seen):
        if not flags:
            raise CapError("empty-set-flags")
        for flag in flags:
            if flag == "a":
                self._add_ambient(result, name, seen)
                continue
            target = _PROCESS_FLAG_TARGETS.get(flag)
            if target is None:
                raise CapError("unknown-set-flag")
            self._add_to_set(result, target, name, seen)

    def _add_ambient(self, result, name, seen):
        inheritable = result["inheritable"]
        permitted = result["permitted"]
        in_inheritable = inheritable is True or name in inheritable
        in_permitted = permitted is True or name in permitted
        if not (in_inheritable and in_permitted):
            raise CapError("ambient-requires-inheritable-and-permitted")
        self._add_to_set(result, "ambient", name, seen)

    def _apply_file_flags(self, name, flags, result, seen):
        if not flags:
            raise CapError("empty-file-flags")
        for flag in flags:
            targets = _FILE_FLAG_TARGETS.get(flag)
            if targets is None:
                raise CapError("unknown-file-flag")
            bool_key, caps_key, process_key = targets
            result[bool_key] = True
            result[caps_key].add(name)
            result[process_key] = True
            seen.add((caps_key, name))

    def _drop_from_bounding(self, name, result):
        result["bounding"].discard(name)
        result["bounding_dropped"].add(name)

    def exec_after(self, process, file_caps=None):
        bounding = _caps_of(process, "bounding")
        dropped = _caps_of(process, "bounding_dropped")
        new_bounding = bounding - dropped
        inheritable = _caps_of(process, "inheritable")
        permitted = _caps_of(process, "permitted")
        ambient = _caps_of(process, "ambient")

        file_permitted = _caps_of(file_caps, "file_permitted_caps")
        file_inheritable = _caps_of(file_caps, "file_inheritable_caps")
        file_effective = bool((file_caps or {}).get("file_effective"))

        warnings = []
        new_permitted = (
            (inheritable & file_inheritable)
            | (permitted & new_bounding)
            | (file_permitted - dropped)
        )
        new_ambient = ambient & inheritable & new_permitted
        lost_ambient = ambient - new_ambient
        if lost_ambient:
            warnings.append(
                "ambient-dropped-%s" % ",".join(sorted(lost_ambient))
            )
        new_effective = set(new_permitted) if file_effective else set(new_ambient)

        exec_after = {
            "permitted": set(new_permitted),
            "effective": set(new_effective),
            "inheritable": set(inheritable),
            "ambient": set(new_ambient),
        }
        return {
            "exec_after": exec_after,
            "bounding": new_bounding,
            "permitted": set(new_permitted),
            "effective": set(new_effective),
            "inheritable": set(inheritable),
            "ambient": set(new_ambient),
            "warnings": warnings,
        }
