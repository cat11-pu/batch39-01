from decimal import Decimal, ROUND_HALF_UP


DEFAULT_ORDER = [
    "crit",
    "flat",
    "percent",
    "shield",
    "vulnerability",
    "final",
]

_NON_NEGATIVE_FIELDS = (
    "base",
    "crit",
    "armor_flat",
    "armor_pct",
    "shield",
    "vulnerability",
    "final_mult",
    "target_hp",
    "min_damage",
    "reflect",
)


def half_up(value):
    return int(Decimal(repr(float(value))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class DamageMitigationChain:
    def __init__(self, order=None, min_damage=0, resist_cap=0.8):
        if min_damage < 0:
            raise ValueError("min_damage must not be negative")
        if not 0 <= resist_cap <= 1:
            raise ValueError("resist_cap must be within [0, 1]")
        self.order = list(order) if order is not None else list(DEFAULT_ORDER)
        self.min_damage = min_damage
        self.resist_cap = resist_cap

    def _validate(self, hit):
        for field in _NON_NEGATIVE_FIELDS:
            if field in hit and hit[field] is not None and hit[field] < 0:
                raise ValueError(f"{field} must not be negative")

    def _resolve_one(self, hit):
        self._validate(hit)

        damage_type = hit.get("damage_type", "physical")
        is_true = damage_type == "true"
        shield_type = hit.get("shield_type", "physical")
        hit_min = hit.get("min_damage", self.min_damage)
        target_hp = hit.get("target_hp", float("inf"))

        working = float(hit["base"])
        shield_absorbed = 0.0

        for stage in self.order:
            if stage == "crit":
                working *= float(hit.get("crit", 1.0))
            elif stage == "flat":
                if not is_true:
                    working = max(0.0, working - float(hit.get("armor_flat", 0.0)))
            elif stage == "percent":
                if not is_true:
                    resist = min(float(hit.get("armor_pct", 0.0)), self.resist_cap)
                    working *= 1.0 - max(0.0, resist)
            elif stage == "shield":
                if not is_true and shield_type == damage_type:
                    available = float(hit.get("shield", 0.0))
                    absorbed = min(working, available)
                    shield_absorbed += absorbed
                    working -= absorbed
            elif stage == "vulnerability":
                working *= float(hit.get("vulnerability", 1.0))
            elif stage == "final":
                working *= float(hit.get("final_mult", 1.0))

        configured_min = float(hit_min) if hit_min is not None else 0.0
        minimum = max(float(self.min_damage), configured_min)
        if working < minimum:
            working = minimum

        final_damage = half_up(working)
        health_loss = min(final_damage, half_up(target_hp))

        reflected = 0.0
        if hit.get("reflect") is not None and health_loss > 0:
            reflected = half_up(health_loss * float(hit["reflect"]))

        overflow = 0.0
        if hit.get("overflow"):
            overflow = max(0, final_damage - health_loss)

        return {
            "damage": final_damage,
            "raw_damage": working,
            "shield_absorbed": half_up(shield_absorbed),
            "reflected": reflected,
            "overflow": overflow,
            "health_loss": health_loss,
            "order": list(self.order),
        }

    def resolve(self, hit):
        return self._resolve_one(hit)

    def resolve_all(self, hits):
        results = [self._resolve_one(hit) for hit in hits]

        raw_total = sum(result["raw_damage"] for result in results)
        per_hit_total = sum(result["damage"] for result in results)
        total_damage = half_up(raw_total)
        rounding_diff = total_damage - per_hit_total

        return {
            "damage": total_damage,
            "per_hit_damage": per_hit_total,
            "rounding_diff": rounding_diff,
            "shield_absorbed": sum(result["shield_absorbed"] for result in results),
            "reflected": sum(result["reflected"] for result in results),
            "overflow": sum(result["overflow"] for result in results),
            "results": results,
            "order": list(self.order),
        }
