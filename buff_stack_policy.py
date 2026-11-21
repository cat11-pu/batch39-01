MODE_REFRESH = "refresh"
MODE_EXTEND = "extend"
MODE_INDEPENDENT = "independent"
MODE_REPLACE = "replace"


class BuffStackPolicy:
    def __init__(self, max_stacks=5, max_sources=3):
        self.max_stacks = max_stacks
        self.max_sources = max_sources
        self._seq = 0

    def _entry(self, target, buff_id):
        return target.setdefault("buffs", {}).setdefault(buff_id, {"layers": []})

    def _now(self, target, now):
        last = target.get("last_tick")
        if last is None or now > last:
            target["last_tick"] = now
        return target["last_tick"]

    def _expire(self, target, now):
        for buff_id in list(target.get("buffs", {}).keys()):
            layers = target["buffs"][buff_id]["layers"]
            expired = [layer for layer in layers if layer["expire_at"] <= now]
            for layer in expired:
                target.setdefault("events", []).append(buff_id + "_expired")
                layer["fired"] = True
            if expired:
                target["buffs"][buff_id]["layers"] = [
                    layer for layer in layers if layer not in expired
                ]
            if not target["buffs"][buff_id]["layers"]:
                del target["buffs"][buff_id]

    def _make_layer(self, source, priority, dispellable, expire_at):
        self._seq += 1
        return {
            "source": source,
            "priority": priority,
            "dispellable": dispellable,
            "expire_at": expire_at,
            "seq": self._seq,
            "fired": False,
        }

    def _sources(self, entry):
        ordered = []
        for layer in entry["layers"]:
            for source in [layer["source"]] + layer.get("extra_sources", []):
                if source not in ordered:
                    ordered.append(source)
        return ordered

    def _stats_snapshot(self, target):
        snapshot = dict(target.get("stats", {}))
        stacks = {}
        remaining = {}
        buffs = {}
        sources = {}
        total_layers = 0
        current = target.get("last_tick", 0)
        for buff_id, entry in target.get("buffs", {}).items():
            layers = entry["layers"]
            total_layers += len(layers)
            stacks[buff_id] = len(layers)
            buffs[buff_id] = layers
            sources[buff_id] = self._sources(entry)
            if layers:
                remaining[buff_id] = max(
                    0, max(layer["expire_at"] - current for layer in layers)
                )
        snapshot["attack"] = snapshot.get("attack", 0) + total_layers
        snapshot["stacks"] = stacks
        snapshot["remaining"] = remaining
        snapshot["buffs"] = buffs
        snapshot["sources"] = sources
        return snapshot

    def apply(
        self,
        target,
        buff_id,
        source,
        mode="refresh",
        duration=10,
        now=0,
        priority=0,
        dispellable=True,
        max_duration=None,
    ):
        target.setdefault("events", [])
        current = self._now(target, now)
        self._expire(target, current)

        if target.get("immune"):
            target.setdefault("immune_attempts", []).append(
                {"buff_id": buff_id, "source": source, "now": current}
            )
            snapshot = self._stats_snapshot(target)
            return {
                "applied": False,
                "attempted": True,
                "before": snapshot,
                "after": self._stats_snapshot(target),
            }

        before = self._stats_snapshot(target)
        entry = self._entry(target, buff_id)
        layers = entry["layers"]
        expire_at = current + duration
        replaced = []

        if mode == MODE_REPLACE:
            for layer in layers:
                target["events"].append(buff_id + "_replaced")
                replaced.append(layer)
            entry["layers"] = [
                self._make_layer(source, priority, dispellable, expire_at)
            ]

        elif mode == MODE_INDEPENDENT:
            existing = next(
                (layer for layer in layers if layer["source"] == source), None
            )
            if existing is not None:
                existing["expire_at"] = expire_at
                existing["priority"] = priority
                existing["dispellable"] = dispellable
            else:
                if len(self._sources(entry)) >= self.max_sources:
                    after = self._stats_snapshot(target)
                    return {
                        "applied": False,
                        "attempted": True,
                        "reason": "source_limit",
                        "before": before,
                        "after": after,
                    }
                if len(layers) >= self.max_stacks:
                    weakest = min(
                        layers, key=lambda layer: (layer["priority"], layer["seq"])
                    )
                    target["events"].append(buff_id + "_replaced")
                    replaced.append(weakest)
                    entry["layers"] = [
                        layer for layer in layers if layer is not weakest
                    ]
                entry["layers"].append(
                    self._make_layer(source, priority, dispellable, expire_at)
                )

        else:
            if not layers:
                entry["layers"] = [
                    self._make_layer(source, priority, dispellable, expire_at)
                ]
            else:
                layer = layers[0]
                if mode == MODE_EXTEND:
                    new_expire = layer["expire_at"] + duration
                    if max_duration is not None:
                        new_expire = min(new_expire, current + max_duration)
                    layer["expire_at"] = new_expire
                else:
                    layer["expire_at"] = expire_at
                layer["priority"] = priority
                layer["dispellable"] = dispellable
                extras = layer.setdefault("extra_sources", [])
                if source != layer["source"] and source not in extras:
                    if len(self._sources(entry)) >= self.max_sources:
                        after = self._stats_snapshot(target)
                        return {
                            "applied": False,
                            "attempted": True,
                            "reason": "source_limit",
                            "before": before,
                            "after": after,
                        }
                    extras.append(source)

        target["events"].append(buff_id + "_applied")
        after = self._stats_snapshot(target)
        return {
            "applied": True,
            "attempted": True,
            "before": before,
            "after": after,
            "replaced": replaced,
        }

    def remove(self, target, buff_id, source=None):
        entry = target.get("buffs", {}).get(buff_id)
        if entry is None:
            return {"removed": []}
        if source is None:
            victims = list(entry["layers"])
        else:
            victims = [
                layer
                for layer in entry["layers"]
                if source == layer["source"]
                or source in layer.get("extra_sources", [])
            ]
        for layer in victims:
            if source is not None and source in layer.get("extra_sources", []):
                layer["extra_sources"].remove(source)
            target.setdefault("events", []).append(buff_id + "_removed")
        entry["layers"] = [layer for layer in entry["layers"] if layer not in victims]
        if not entry["layers"]:
            del target["buffs"][buff_id]
        return {"removed": victims}

    def dispel(self, target, priority=0):
        candidates = []
        for buff_id, entry in target.get("buffs", {}).items():
            for layer in entry["layers"]:
                if layer["dispellable"] and layer["priority"] <= priority:
                    candidates.append((buff_id, layer))
        candidates.sort(key=lambda item: (item[1]["priority"], item[1]["seq"]))
        removed_ids = []
        for buff_id, layer in candidates:
            entry = target["buffs"].get(buff_id)
            if entry is None or layer not in entry["layers"]:
                continue
            entry["layers"].remove(layer)
            target.setdefault("events", []).append(buff_id + "_removed")
            removed_ids.append(buff_id)
            if not entry["layers"]:
                del target["buffs"][buff_id]
        return removed_ids

    def tick(self, target, now):
        current = self._now(target, now)
        self._expire(target, current)
        return self.stats(target)

    def stats(self, target):
        return self._stats_snapshot(target)
