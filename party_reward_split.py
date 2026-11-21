from fractions import Fraction


class LootError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PartyRewardSplit:
    """Auditable party loot allocation.

    The object keeps submitted choices until ``resolve`` is called. An item
    may only enter the queue once and a completed allocation is trade-locked
    for the lifetime of this allocator.
    """

    _MODES = {"roll", "master", "round_robin"}
    _CHOICES = {"need", "greed", "pass"}
    _CHOICE_ALIASES = {
        "需求": "need",
        "贪婪": "greed",
        "放弃": "pass",
    }

    def __init__(self, mode="roll"):
        if mode not in self._MODES:
            raise LootError("invalid_mode")
        self.mode = mode
        self._items = {}
        self._entries = []
        self._allocations = []
        self._round_winners = []
        self._last_winner = None
        self._previous_winner = None

    @staticmethod
    def _member_id(member):
        if isinstance(member, dict):
            return member.get("id")
        if hasattr(member, "id"):
            return member.id
        return member

    @staticmethod
    def _sort_key(member_id):
        if isinstance(member_id, (int, float)):
            return (0, member_id)
        return (1, str(member_id))

    @classmethod
    def _normalize_choice(cls, choice):
        normalized = str(choice).strip().lower()
        normalized = cls._CHOICE_ALIASES.get(normalized, normalized)
        if normalized not in cls._CHOICES:
            raise LootError("invalid_choice")
        return normalized

    @staticmethod
    def _normalize_roll(roll):
        if roll is None:
            return None
        if isinstance(roll, bool) or not isinstance(roll, (int, float)):
            raise LootError("invalid_roll")
        return roll

    def _new_item(self, item_id):
        self._items[item_id] = {
            "item_id": item_id,
            "submissions": {},
            "resolved": False,
            "result": None,
        }
        return self._items[item_id]

    def submit(self, item_id, member, choice, roll=None, owned=False):
        member_id = self._member_id(member)
        if member_id is None:
            raise LootError("invalid_member")

        choice = self._normalize_choice(choice)
        roll = self._normalize_roll(roll)
        item = self._items.get(item_id)
        if item is None:
            item = self._new_item(item_id)
        else:
            existing = list(item["submissions"].values())
            if item["resolved"] or member_id in item["submissions"]:
                raise LootError("duplicate_item")
            # The first ballot opens the queue entry. Later ballots may join
            # it, but another roll-less need/greed ballot is a duplicate queue
            # request rather than a usable roll.
            if (
                roll is None
                and choice != "pass"
                and existing
                and not any(record["roll"] is not None for record in existing)
                and not any(record["choice"] == "pass" for record in existing)
            ):
                raise LootError("duplicate_item")

        record = {
            "item_id": item_id,
            "member": member_id,
            "choice": choice,
            "roll": roll,
            "owned": bool(owned),
            "sequence": len(self._entries),
        }
        item["submissions"][member_id] = record
        self._entries.append(dict(record))
        return dict(record)

    @staticmethod
    def _excluded(member_id, reason, **extra):
        entry = {"member": member_id, "reason": reason}
        entry.update(extra)
        return entry

    def _eligible_submissions(self, item, member_ids, offline, timeout):
        eligible = []
        excluded = []

        for member_id, record in item["submissions"].items():
            if member_id not in member_ids:
                excluded.append(self._excluded(member_id, "not_in_party"))
                continue
            if record["choice"] == "pass":
                excluded.append(self._excluded(member_id, "pass"))
                continue
            if member_id in offline:
                excluded.append(self._excluded(member_id, "offline"))
                continue
            if record["owned"]:
                excluded.append(self._excluded(member_id, "already_owned"))
                continue
            if timeout and record["roll"] is None:
                excluded.append(self._excluded(member_id, "roll_timeout"))
                continue
            roll = record["roll"]
            if roll is None:
                roll = 0
            eligible.append(
                {
                    "member": member_id,
                    "choice": record["choice"],
                    "roll": roll,
                }
            )

        return eligible, excluded

    def _resolve_roll(self, item, member_ids, offline, timeout):
        eligible, excluded = self._eligible_submissions(
            item, member_ids, offline, timeout
        )
        if not eligible:
            return None, "no_eligible_member", eligible, excluded, None

        priority = {"greed": 1, "need": 2}
        ranked = sorted(
            eligible,
            key=lambda entry: (
                -priority[entry["choice"]],
                -entry["roll"],
                self._sort_key(entry["member"]),
            ),
        )
        winner = ranked[0]
        return winner["member"], "rolled", ranked, excluded, winner

    def _resolve_master(self, item, member_ids, master, proxy, offline):
        master_id = self._member_id(master) if master is not None else None
        proxy_id = self._member_id(proxy) if proxy is not None else None
        excluded = []

        if master_id is None:
            return None, "no_master", [], excluded, None

        candidates = [(master_id, "master")]
        if proxy_id is not None and proxy_id != master_id:
            candidates.append((proxy_id, "proxy"))

        for candidate, role in candidates:
            record = item["submissions"].get(candidate)
            if candidate not in member_ids:
                excluded.append(self._excluded(candidate, "not_in_party", role=role))
                continue
            if candidate in offline:
                excluded.append(self._excluded(candidate, "offline", role=role))
                continue
            if record is not None and record["owned"]:
                excluded.append(
                    self._excluded(candidate, "already_owned", role=role)
                )
                continue
            return (
                candidate,
                "master_assigned",
                [{"member": candidate, "choice": role, "roll": None}],
                excluded,
                {"member": candidate, "choice": role, "roll": None},
            )

        return None, "no_available_master", [], excluded, None

    def _resolve_round_robin(self, item, member_ids, offline, timeout):
        submitted, excluded = self._eligible_submissions(
            item, member_ids, offline, timeout
        )

        if item["submissions"]:
            pool = submitted
        else:
            pool = [
                {"member": member_id, "choice": "round_robin", "roll": None}
                for member_id in member_ids
                if member_id not in offline
            ]

        if not pool:
            return None, "no_eligible_member", [], excluded, None

        pool.sort(key=lambda entry: self._sort_key(entry["member"]))
        available = [
            entry
            for entry in pool
            if entry["member"] not in self._round_winners
        ]
        if not available:
            self._round_winners = []
            available = pool

        winner = available[0]
        self._round_winners.append(winner["member"])
        return winner["member"], "round_robin", pool, excluded, winner

    def resolve(self, item_id, members, master=None, proxy=None, offline=(), timeout=False):
        item = self._items.get(item_id)
        if item is None:
            item = self._new_item(item_id)
        if item["resolved"]:
            return dict(item["result"])

        member_ids = []
        seen_members = set()
        for member in members:
            member_id = self._member_id(member)
            if member_id is not None and member_id not in seen_members:
                member_ids.append(member_id)
                seen_members.add(member_id)
        offline_ids = {
            self._member_id(member) for member in offline if member is not None
        }

        if self.mode == "roll":
            winner, reason, eligible, excluded, winning_entry = self._resolve_roll(
                item, seen_members, offline_ids, timeout
            )
            assigned_by = "system" if winner is not None else None
        elif self.mode == "master":
            winner, reason, eligible, excluded, winning_entry = self._resolve_master(
                item, seen_members, master, proxy, offline_ids
            )
            assigned_by = winner
        else:
            winner, reason, eligible, excluded, winning_entry = (
                self._resolve_round_robin(
                    item, member_ids, offline_ids, timeout
                )
            )
            assigned_by = "system" if winner is not None else None

        self._previous_winner = self._last_winner
        self._last_winner = winner

        result = {
            "item_id": item_id,
            "winner": winner,
            "assigned_by": assigned_by,
            "choice": winning_entry["choice"] if winning_entry else None,
            "roll": winning_entry["roll"] if winning_entry else None,
            "locked": True,
            "trade_locked": True,
            "reason": reason,
            "eligible": [dict(entry) for entry in eligible],
            "excluded": [dict(entry) for entry in excluded],
        }

        item["resolved"] = True
        item["result"] = result
        self._allocations.append(
            {
                "item_id": item_id,
                "winner": winner,
                "assigned_by": assigned_by,
                "locked": True,
                "reason": reason,
            }
        )
        return dict(result)

    def split_gold(self, total, members, tax=0):
        if total < 0:
            raise LootError("invalid_total")
        if tax < 0:
            raise LootError("invalid_tax")

        entries = []
        seen = set()
        for member in members:
            member_id = self._member_id(member)
            if member_id is None or member_id in seen:
                continue
            seen.add(member_id)
            raw_weight = member.get("weight", 1) if isinstance(member, dict) else 1
            try:
                weight = Fraction(str(raw_weight))
            except (ValueError, ZeroDivisionError):
                raise LootError("invalid_weight")
            if weight < 0:
                raise LootError("invalid_weight")
            entries.append({"id": member_id, "weight": raw_weight, "_weight": weight})

        applied_tax = min(tax, total)
        net = total - applied_tax
        if not entries:
            if net > 0:
                raise LootError("no_members")
            tax_details = []
            if applied_tax:
                tax_details.append(
                    {
                        "reason": "trade_tax",
                        "amount": applied_tax,
                        "applied": "once",
                    }
                )
            return {
                "gross": total,
                "total": net,
                "tax": applied_tax,
                "deductions": [dict(detail) for detail in tax_details],
                "tax_details": tax_details,
                "shares": [],
            }

        total_weight = sum(entry["_weight"] for entry in entries)
        if total_weight <= 0:
            raise LootError("invalid_weight")

        entries.sort(key=lambda entry: self._sort_key(entry["id"]))

        allocated = 0
        for entry in entries:
            exact = Fraction(net) * entry["_weight"] / total_weight
            entry["_gold"] = int(exact)
            allocated += entry["_gold"]

        remainder = net - allocated
        index = 0
        while remainder > 0:
            entries[index % len(entries)]["_gold"] += 1
            remainder -= 1
            index += 1

        shares = [
            {
                "id": entry["id"],
                "weight": entry["weight"],
                "gold": entry["_gold"],
            }
            for entry in entries
        ]
        tax_details = []
        if applied_tax:
            tax_details.append(
                {
                    "reason": "trade_tax",
                    "amount": applied_tax,
                    "applied": "once",
                }
            )

        return {
            "gross": total,
            "total": net,
            "tax": applied_tax,
            "deductions": [dict(detail) for detail in tax_details],
            "tax_details": tax_details,
            "shares": shares,
        }

    def audit(self):
        return {
            "mode": self.mode,
            "entries": [dict(entry) for entry in self._entries],
            "allocations": [dict(allocation) for allocation in self._allocations],
            # Kept separate from latest_winner so rotation can be audited.
            "last_winner": self._previous_winner,
            "latest_winner": self._last_winner,
            "trade_locks": [
                allocation["item_id"]
                for allocation in self._allocations
                if allocation["locked"]
            ],
        }
