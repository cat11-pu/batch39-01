"""Auditable net-difference planning for IAM-style permission policies."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


# A deliberately small but useful action look-up table. Wildcards are first
# resolved against actions explicitly mentioned by either policy, so a change
# such as ``s3:*`` -> ``s3:GetObject`` does not invent actions that were never
# part of either document. The table is the fallback when a wildcard appears
# without a concrete counterpart.
_KNOWN_ACTION_NAMES = (
    "cloudtrail:DeleteTrail",
    "cloudtrail:PutEventSelectors",
    "cloudtrail:StopLogging",
    "cloudwatch:DeleteAlarms",
    "dynamodb:DeleteItem",
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:CreateSecurityGroup",
    "ec2:DeleteSecurityGroup",
    "ec2:DescribeInstances",
    "ec2:ModifyInstanceAttribute",
    "ec2:RunInstances",
    "ec2:TerminateInstances",
    "ecr:DeleteRepository",
    "iam:AttachUserPolicy",
    "iam:CreateAccessKey",
    "iam:CreateRole",
    "iam:CreateUser",
    "iam:DeleteAccessKey",
    "iam:DeleteRole",
    "iam:DeleteUser",
    "iam:DetachUserPolicy",
    "iam:GetUser",
    "iam:ListAccessKeys",
    "iam:ListUsers",
    "iam:PassRole",
    "iam:PutUserPolicy",
    "iam:UpdateAccessKey",
    "iam:UpdateAssumeRolePolicy",
    "kms:CreateKey",
    "kms:Decrypt",
    "kms:Encrypt",
    "kms:ScheduleKeyDeletion",
    "lambda:CreateFunction",
    "lambda:DeleteFunction",
    "lambda:InvokeFunction",
    "lambda:UpdateFunctionCode",
    "logs:DeleteLogGroup",
    "rds:DeleteDBInstance",
    "rds:ModifyDBInstance",
    "s3:CreateBucket",
    "s3:DeleteBucket",
    "s3:DeleteObject",
    "s3:GetBucketPolicy",
    "s3:GetObject",
    "s3:ListBucket",
    "s3:PutBucketPolicy",
    "s3:PutObject",
    "secretsmanager:DeleteSecret",
    "secretsmanager:GetSecretValue",
    "sns:Publish",
    "sqs:DeleteMessage",
    "sqs:ReceiveMessage",
    "sqs:SendMessage",
    "ssm:SendCommand",
    "sts:AssumeRole",
    "sts:GetCallerIdentity",
)

_KNOWN_ACTIONS = {name.casefold(): name for name in _KNOWN_ACTION_NAMES}

_BUILTIN_HIGH_RISK = (
    "iam:AttachUserPolicy",
    "iam:CreateAccessKey",
    "iam:CreateRole",
    "iam:CreateUser",
    "iam:DeleteRole",
    "iam:DeleteUser",
    "iam:PassRole",
    "iam:PutUserPolicy",
    "iam:UpdateAssumeRolePolicy",
    "kms:ScheduleKeyDeletion",
    "s3:DeleteBucket",
    "s3:PutBucketPolicy",
    "cloudtrail:DeleteTrail",
    "cloudtrail:StopLogging",
)


@dataclass(frozen=True)
class _Atomic:
    """One effective (effect, principal, action, resource, condition) tuple."""

    effect: str
    principal: str
    principal_key: str
    principal_type: str
    principal_name_key: str
    action: str
    action_key: str
    resource: str
    condition_key: tuple
    condition_display: tuple
    unknown: bool = False

    @property
    def key(self) -> tuple:
        return (
            self.effect,
            self.principal_key,
            self.action_key,
            self.resource,
            self.condition_key,
        )


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _normalize_resource(value: Any) -> str:
    text = str(value).strip().casefold()
    if not text:
        return ""
    # Keep the scheme separator intact while folding repeated path slashes.
    if "://" in text:
        scheme, remainder = text.split("://", 1)
        remainder = re.sub(r"/{2,}", "/", remainder)
        return scheme + "://" + remainder
    return re.sub(r"/{2,}", "/", text)


def _has_wildcard(value: str) -> bool:
    return "*" in value or "?" in value


def _glob_regex(pattern: str) -> re.Pattern:
    expression = re.escape(pattern)
    expression = expression.replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(r"\A" + expression + r"\Z", re.DOTALL)


def _static_prefix(pattern: str) -> str:
    positions = [pos for pos in (pattern.find("*"), pattern.find("?")) if pos >= 0]
    return pattern[: min(positions)] if positions else pattern


def _static_suffix(pattern: str) -> str:
    positions = [pos for pos in (pattern.rfind("*"), pattern.rfind("?")) if pos >= 0]
    return pattern[max(positions) + 1 :] if positions else pattern


def _resource_covers(broad: str, narrow: str) -> bool:
    """Best-effort subset check for normalized resource globs."""

    if broad == narrow:
        return True
    if broad == "*":
        return True
    if not _has_wildcard(broad):
        return False

    if not _has_wildcard(narrow):
        return _glob_regex(broad).match(narrow) is not None

    broad_prefix = _static_prefix(broad)
    narrow_prefix = _static_prefix(narrow)
    if not narrow_prefix.startswith(broad_prefix):
        return False

    broad_suffix = _static_suffix(broad)
    narrow_suffix = _static_suffix(narrow)
    if broad_suffix and not narrow_suffix.endswith(broad_suffix):
        return False
    return True


def _resource_direction(before: str, after: str) -> str:
    after_is_subset = _resource_covers(before, after)
    before_is_subset = _resource_covers(after, before)
    if after_is_subset and not before_is_subset:
        return "narrowed"
    if before_is_subset and not after_is_subset:
        return "widened"
    return "modified"


def _values_tuple(value: Any) -> tuple:
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted({str(item) for item in value}))
    return (str(value),)


def _condition_items(condition: Any) -> tuple:
    """Flatten a condition into sorted, displayable (operator, key, values)."""

    if not condition:
        return ()
    if isinstance(condition, str):
        try:
            condition = json.loads(condition)
        except (TypeError, ValueError):
            return (("Condition", condition, (str(condition),)),)
    if not isinstance(condition, dict):
        return ()

    items = []
    for operator, body in condition.items():
        if isinstance(body, dict):
            for key, value in body.items():
                items.append((str(operator), str(key), _values_tuple(value)))
        else:
            items.append((str(operator), str(operator), _values_tuple(body)))

    return tuple(
        sorted(items, key=lambda item: (item[0].casefold(), item[1].casefold(), item[2]))
    )


def _condition_key(items: tuple) -> tuple:
    return tuple(
        (operator.casefold(), key.casefold(), values)
        for operator, key, values in items
    )


def _condition_to_dict(items: tuple) -> dict:
    result: dict = {}
    for operator, key, values in sorted(
        items, key=lambda item: (item[0].casefold(), item[1].casefold(), item[2])
    ):
        value: Any = values[0] if len(values) == 1 else list(values)
        result.setdefault(operator, {})[key] = value
    return result


def _condition_diff(before_items: tuple, after_items: tuple) -> dict:
    before = {
        (operator.casefold(), key.casefold()): (operator, key, values)
        for operator, key, values in before_items
    }
    after = {
        (operator.casefold(), key.casefold()): (operator, key, values)
        for operator, key, values in after_items
    }

    added = []
    for identity in sorted(after):
        if identity not in before:
            operator, key, values = after[identity]
            added.append(
                {"operator": operator, "key": key, "values": list(values)}
            )

    removed = []
    for identity in sorted(before):
        if identity not in after:
            operator, key, values = before[identity]
            removed.append(
                {"operator": operator, "key": key, "values": list(values)}
            )

    changed = []
    for identity in sorted(set(before) & set(after)):
        before_entry = before[identity]
        after_entry = after[identity]
        if before_entry[2] != after_entry[2]:
            changed.append(
                {
                    "operator": after_entry[0],
                    "key": after_entry[1],
                    "before": list(before_entry[2]),
                    "after": list(after_entry[2]),
                }
            )

    return {
        "condition_added": added,
        "condition_removed": removed,
        "condition_changed": changed,
    }


def _condition_is_subset(deny_items: tuple, allow_items: tuple) -> bool:
    """Whether a deny condition can be satisfied by the same request."""

    if not deny_items:
        return True
    if not allow_items:
        return True
    allow = {
        (operator.casefold(), key.casefold(), values)
        for operator, key, values in allow_items
    }
    return all(
        (operator.casefold(), key.casefold(), values) in allow
        for operator, key, values in deny_items
    )


def _principal_values(value: Any) -> list[str]:
    if value is None:
        return ["*"]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else ["*"]
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_principal_values(item))
        return sorted(set(result), key=str.casefold) or ["*"]
    if isinstance(value, dict):
        if "type" in value and "name" in value:
            return [f"{value['type']}:{value['name']}"]
        result = []
        for principal_type, principals in sorted(
            value.items(), key=lambda item: str(item[0])
        ):
            type_text = str(principal_type).casefold()
            for principal in _as_list(principals):
                text = str(principal).strip()
                if not text:
                    continue
                if type_text == "aws":
                    result.append(text)
                else:
                    result.append(f"{type_text}:{text}")
        return sorted(set(result), key=str.casefold) or ["*"]
    return [str(value)]


def _principal_parts(value: str) -> tuple[str, str, str, str]:
    principal = str(value).strip()
    key = principal.casefold()
    if key in ("", "*"):
        return principal or "*", key or "*", "*", "*"

    if key.startswith("arn:"):
        parts = principal.split(":")
        if len(parts) >= 6:
            resource = ":".join(parts[5:])
            principal_type = resource.split("/", 1)[0].casefold()
            name = resource.split("/", 1)[1] if "/" in resource else ""
            return principal, key, principal_type, name.casefold()

    if ":" in principal:
        principal_type, name = principal.split(":", 1)
        return principal, key, principal_type.casefold(), name.casefold()

    return principal, key, "principal", key


def _statement_values(statement: dict, keys: Iterable[str]) -> list:
    for key in keys:
        if key in statement:
            return _as_list(statement[key])
    return []


def _version_from_policy(policy: Any) -> Any:
    if not isinstance(policy, dict):
        return None
    for key in (
        "VersionId",
        "version_id",
        "versionId",
        "PolicyVersion",
        "policy_version",
        "version",
        "Version",
    ):
        if key in policy:
            return policy[key]
    return None


def _extract_statements(policy: Any) -> tuple[list[dict], Any]:
    if policy is None:
        return [], None

    version = _version_from_policy(policy)
    if isinstance(policy, str):
        try:
            policy = json.loads(policy)
        except (TypeError, ValueError):
            return [], version
        version = _version_from_policy(policy)

    if isinstance(policy, (list, tuple)):
        # Also accept (version, statements) pairs for callers that carry the
        # document version separately from the statement list.
        if (
            len(policy) == 2
            and not isinstance(policy[0], dict)
            and isinstance(policy[1], (list, tuple, dict))
        ):
            return _extract_statements(policy[1])[0], policy[0]
        return [item for item in policy if isinstance(item, dict)], version

    if isinstance(policy, dict):
        for key in ("Statement", "statement", "Statements", "statements"):
            if key in policy:
                statements = _as_list(policy[key])
                return [item for item in statements if isinstance(item, dict)], version

        if any(
            key in policy
            for key in ("effect", "Effect", "action", "Action", "not_action", "NotAction")
        ):
            return [policy], version

    return [], version


def _collect_observed(statements: list[dict]) -> tuple[set[str], dict[str, str], set[str]]:
    actions: set[str] = set()
    action_display: dict[str, str] = {}
    resources: set[str] = set()

    for statement in statements:
        normal_actions = _statement_values(
            statement, ("action", "Action", "actions", "Actions")
        )
        not_actions = _statement_values(
            statement,
            ("not_action", "NotAction", "notAction", "Not_Action", "notActions", "NotActions"),
        )

        for value in normal_actions + not_actions:
            for expression in _as_list(value):
                expression = str(expression).strip()
                if expression.casefold().startswith("notaction:"):
                    expression = expression.split(":", 1)[1].strip()
                if not expression or _has_wildcard(expression):
                    continue
                key = expression.casefold()
                actions.add(key)
                if key not in action_display or expression < action_display[key]:
                    action_display[key] = expression

        resource_values = _statement_values(
            statement, ("resource", "Resource", "resources", "Resources")
        ) + _statement_values(
            statement,
            (
                "not_resource",
                "NotResource",
                "notResource",
                "Not_Resource",
                "notResources",
                "NotResources",
            ),
        )
        for value in resource_values:
            for resource in _as_list(value):
                normalized = _normalize_resource(resource)
                if normalized:
                    resources.add(normalized)

    return actions, action_display, resources


def _expand_action(
    expression: str, observed: set[str], known_actions: dict[str, str]
) -> set[str]:
    key = expression.casefold()
    if not _has_wildcard(key):
        return {key}

    observed_matches = {
        action for action in observed if fnmatch.fnmatchcase(action, key)
    }
    if observed_matches:
        return observed_matches

    known_matches = {
        action for action in known_actions if fnmatch.fnmatchcase(action, key)
    }
    if known_matches:
        return known_matches
    return {key}


def _expand_action_fully(
    expression: str, observed: set[str], known_actions: dict[str, str]
) -> set[str]:
    """Expand a newly granted wildcard across the complete lookup table."""

    key = expression.casefold()
    if not _has_wildcard(key):
        return {key}

    known_matches = {
        action for action in known_actions if fnmatch.fnmatchcase(action, key)
    }
    observed_matches = {
        action for action in observed if fnmatch.fnmatchcase(action, key)
    }
    matches = known_matches | observed_matches
    return matches or {key}


def _expand_against(expression: str, universe: set[str]) -> set[str]:
    key = expression.casefold()
    if not _has_wildcard(key):
        return {key}
    matches = {action for action in universe if fnmatch.fnmatchcase(action, key)}
    return matches or {key}


def _display_action(
    action_key: str, observed_display: dict[str, str], fallback: str | None = None
) -> str:
    if action_key in _KNOWN_ACTIONS:
        return _KNOWN_ACTIONS[action_key]
    if action_key in observed_display:
        return observed_display[action_key]
    if fallback is not None:
        return fallback
    return action_key


def _build_atoms(
    statements: list[dict],
    observed_actions: set[str],
    observed_action_display: dict[str, str],
    observed_resources: set[str],
    known_actions: dict[str, str],
    expand_new_wildcards: bool = False,
) -> dict[tuple, _Atomic]:
    atoms: dict[tuple, _Atomic] = {}

    for statement in statements:
        effect = str(
            statement.get("effect", statement.get("Effect", "allow"))
        ).casefold()

        normal_action_values = _statement_values(
            statement, ("action", "Action", "actions", "Actions")
        )
        not_action_values = _statement_values(
            statement,
            ("not_action", "NotAction", "notAction", "Not_Action", "notActions", "NotActions"),
        )

        normal_expressions = []
        for value in normal_action_values:
            for expression in _as_list(value):
                expression = str(expression).strip()
                if not expression:
                    continue
                if expression.casefold().startswith("notaction:"):
                    not_action_values.append(
                        expression.split(":", 1)[1].strip()
                    )
                else:
                    normal_expressions.append(expression)

        not_expressions = []
        for value in not_action_values:
            for expression in _as_list(value):
                expression = str(expression).strip()
                if expression:
                    not_expressions.append(expression)

        action_keys: dict[str, bool] = {}
        for expression in normal_expressions:
            if expand_new_wildcards:
                expanded_actions = _expand_action_fully(
                    expression, observed_actions, known_actions
                )
            else:
                expanded_actions = _expand_action(
                    expression, observed_actions, known_actions
                )
            for action in expanded_actions:
                action_keys[action] = action_keys.get(action, False) or (
                    action not in known_actions
                )
                observed_action_display.setdefault(
                    action,
                    _display_action(action, observed_action_display, expression),
                )

        if not_expressions:
            universe = set(observed_actions) | set(known_actions)
            excluded: set[str] = set()
            for expression in not_expressions:
                excluded |= _expand_against(expression, universe)
            for action in universe - excluded:
                action_keys[action] = action not in known_actions
                observed_action_display.setdefault(
                    action, _display_action(action, observed_action_display)
                )

        resources = []
        for value in _statement_values(
            statement, ("resource", "Resource", "resources", "Resources")
        ):
            for resource in _as_list(value):
                normalized = _normalize_resource(resource)
                if normalized:
                    resources.append(normalized)

        not_resources = []
        for value in _statement_values(
            statement,
            (
                "not_resource",
                "NotResource",
                "notResource",
                "Not_Resource",
                "notResources",
                "NotResources",
            ),
        ):
            for resource in _as_list(value):
                normalized = _normalize_resource(resource)
                if normalized:
                    not_resources.append(normalized)

        if not_resources:
            universe = set(observed_resources) or {"*"}
            effective_resources = {
                resource
                for resource in universe
                if not any(
                    _resource_covers(excluded, resource)
                    for excluded in not_resources
                )
            }
            resources.extend(sorted(effective_resources))

        if not resources:
            resources = ["*"]

        condition_items = _condition_items(
            statement.get("condition", statement.get("Condition", {}))
        )
        condition_key = _condition_key(condition_items)

        principal_values = _statement_values(
            statement, ("principal", "Principal", "principals", "Principals")
        )
        if not principal_values:
            principal_values = ["*"]

        principals = []
        for principal_value in principal_values:
            for principal in _principal_values(principal_value):
                principals.append(_principal_parts(principal))

        for principal, principal_key, principal_type, principal_name_key in principals:
            for action in sorted(action_keys):
                action_display = _display_action(
                    action, observed_action_display, observed_action_display.get(action)
                )
                for resource in sorted(set(resources)):
                    atom = _Atomic(
                        effect=effect,
                        principal=principal,
                        principal_key=principal_key,
                        principal_type=principal_type,
                        principal_name_key=principal_name_key,
                        action=action_display,
                        action_key=action,
                        resource=resource,
                        condition_key=condition_key,
                        condition_display=condition_items,
                        unknown=bool(action_keys.get(action, False)),
                    )
                    existing = atoms.get(atom.key)
                    if existing is None or _atom_display_key(atom) < _atom_display_key(
                        existing
                    ):
                        atoms[atom.key] = atom

    return atoms


def _atom_display_key(atom: _Atomic) -> tuple:
    return (
        atom.principal.casefold(),
        atom.action.casefold(),
        atom.resource,
        atom.effect,
        repr(atom.condition_display),
    )


def _base_item(atom: _Atomic, high_risk: set[str]) -> dict:
    return {
        "principal": atom.principal,
        "action": atom.action,
        "resource": atom.resource,
        "effect": atom.effect,
        "condition": _condition_to_dict(atom.condition_display),
        "high_risk": atom.action_key in high_risk,
    }


def _sort_key(item: dict) -> tuple:
    principal = (
        item.get("principal")
        or item.get("principal_after")
        or item.get("principal_before")
        or ""
    )
    action = item.get("action") or ""
    resource = (
        item.get("resource")
        or item.get("resource_after")
        or item.get("resource_before")
        or ""
    )
    return (
        str(principal).casefold(),
        str(action).casefold(),
        str(resource),
        str(item.get("effect", "")).casefold(),
        repr(item.get("condition", {})),
    )


def _sorted_items(items: Iterable[dict]) -> list[dict]:
    return sorted(items, key=_sort_key)


def _changed_item(
    before: _Atomic,
    after: _Atomic,
    high_risk: set[str],
    change: str = "modified",
) -> dict:
    condition_diff = _condition_diff(
        before.condition_display, after.condition_display
    )
    direction = (
        _resource_direction(before.resource, after.resource)
        if before.resource != after.resource
        else "modified"
    )

    changes = []
    if before.resource != after.resource:
        changes.append(f"resource_{direction}")
    for entry in condition_diff["condition_added"]:
        changes.append(f"condition_added:{entry['operator']}:{entry['key']}")
    for entry in condition_diff["condition_removed"]:
        changes.append(f"condition_removed:{entry['operator']}:{entry['key']}")
    for entry in condition_diff["condition_changed"]:
        changes.append(f"condition_changed:{entry['operator']}:{entry['key']}")

    item = _base_item(after, high_risk)
    item.update(
        {
            "change": change,
            "direction": direction,
            "scope": direction,
            "resource_before": before.resource,
            "resource_after": after.resource,
            "before": _base_item(before, high_risk),
            "after": _base_item(after, high_risk),
            "changes": changes,
        }
    )
    item.update(condition_diff)
    return item


def _replacement_item(before: _Atomic, after: _Atomic, high_risk: set[str]) -> dict:
    item = _base_item(after, high_risk)
    item.update(
        {
            "change": "replaced",
            "replacement": True,
            "principal_before": before.principal,
            "principal_after": after.principal,
            "before": _base_item(before, high_risk),
            "after": _base_item(after, high_risk),
        }
    )
    return item


def _pair_modified(
    removed: list[_Atomic], added: list[_Atomic]
) -> tuple[list[tuple[_Atomic, _Atomic]], list[_Atomic], list[_Atomic]]:
    """Pair same-action removals/additions so field edits are modifications."""

    pairs = []
    remaining_removed = list(removed)
    remaining_added = list(added)

    while remaining_removed and remaining_added:
        best: tuple[int, int, int] | None = None
        best_pair: tuple[_Atomic, _Atomic] | None = None

        for removed_index, before in enumerate(remaining_removed):
            for added_index, after in enumerate(remaining_added):
                if (
                    before.effect != after.effect
                    or before.principal_key != after.principal_key
                    or before.action_key != after.action_key
                ):
                    continue
                score = 0
                if before.resource == after.resource:
                    score += 4
                elif _resource_covers(
                    before.resource, after.resource
                ) or _resource_covers(after.resource, before.resource):
                    score += 2
                if before.condition_key == after.condition_key:
                    score += 2
                candidate = (-score, removed_index, added_index)
                if best is None or candidate < best:
                    best = candidate
                    best_pair = (before, after)

        if best_pair is None:
            break

        pairs.append(best_pair)
        remaining_removed.remove(best_pair[0])
        remaining_added.remove(best_pair[1])

    return pairs, remaining_removed, remaining_added


def _deny_overrides(deny: _Atomic, allow: _Atomic) -> bool:
    if deny.effect != "deny" or allow.effect != "allow":
        return False
    if deny.principal_key != allow.principal_key:
        return False
    if deny.action_key != allow.action_key:
        return False
    if not _resource_covers(deny.resource, allow.resource):
        return False
    return _condition_is_subset(deny.condition_display, allow.condition_display)


def _overriding_denies(
    atom: _Atomic, denies: dict[tuple, _Atomic]
) -> list[_Atomic]:
    return [deny for deny in denies.values() if _deny_overrides(deny, atom)]


def _effective_count(
    atoms: dict[tuple, _Atomic], denies: dict[tuple, _Atomic]
) -> int:
    count = 0
    for atom in atoms.values():
        if atom.effect != "allow" or atom.unknown:
            continue
        if _overriding_denies(atom, denies):
            continue
        count += 1
    return count


def _version_note(before_version: Any, after_version: Any) -> str:
    if before_version is None and after_version is None:
        return (
            "No policy version metadata was provided; "
            "no implicit version change detected."
        )
    if before_version == after_version:
        return (
            f"Policy version {before_version!r} is unchanged; "
            "no implicit version change detected."
        )

    relation = "changed"
    try:
        if int(after_version) > int(before_version):
            relation = "upgraded"
        elif int(after_version) < int(before_version):
            relation = "downgraded"
    except (TypeError, ValueError):
        try:
            if str(after_version) > str(before_version):
                relation = "upgraded"
            elif str(after_version) < str(before_version):
                relation = "downgraded"
        except TypeError:
            pass

    return (
        f"Policy version {relation} from {before_version!r} to {after_version!r}; "
        "implicit changes introduced by the version transition require review."
    )


def _dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        marker = json.dumps(item, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


class PermissionDiffPlan:
    def __init__(self, high_risk=(), **kwargs):
        # ``kwargs`` keeps the class tolerant of callers passing optional
        # version metadata while preserving the original public constructor.
        self._extra_options = dict(kwargs)
        names = list(_BUILTIN_HIGH_RISK) + [str(item) for item in high_risk]
        self.high_risk = {name.casefold() for name in names}

        # Custom high-risk actions are known to the caller even if they are not
        # in the module's standard action table.
        self._known_actions = dict(_KNOWN_ACTIONS)
        for name in self.high_risk:
            self._known_actions.setdefault(name, name)

    def diff(self, before, after):
        before_statements, before_version = _extract_statements(before)
        after_statements, after_version = _extract_statements(after)

        observed_actions, action_display, observed_resources = _collect_observed(
            before_statements + after_statements
        )

        before_atoms = _build_atoms(
            before_statements,
            observed_actions,
            action_display,
            observed_resources,
            self._known_actions,
        )
        after_atoms = _build_atoms(
            after_statements,
            observed_actions,
            action_display,
            observed_resources,
            self._known_actions,
            expand_new_wildcards=True,
        )

        before_denies = {
            key: atom for key, atom in before_atoms.items() if atom.effect == "deny"
        }
        after_denies = {
            key: atom for key, atom in after_atoms.items() if atom.effect == "deny"
        }
        before_allows = {
            key: atom
            for key, atom in before_atoms.items()
            if atom.effect == "allow" and not atom.unknown
        }
        after_allows = {
            key: atom
            for key, atom in after_atoms.items()
            if atom.effect == "allow" and not atom.unknown
        }

        removed_keys = set(before_allows) - set(after_allows)
        added_keys = set(after_allows) - set(before_allows)
        removed_atoms = [before_allows[key] for key in removed_keys]
        added_atoms = [after_allows[key] for key in added_keys]

        replaced = []
        replacement_removed = set()
        replacement_added = set()
        sorted_removed = sorted(removed_atoms, key=_atom_display_key)
        sorted_added = sorted(added_atoms, key=_atom_display_key)

        for before_atom in sorted_removed:
            for after_atom in sorted_added:
                if id(after_atom) in replacement_added:
                    continue
                if (
                    before_atom.effect != after_atom.effect
                    or before_atom.action_key != after_atom.action_key
                    or before_atom.resource != after_atom.resource
                    or before_atom.condition_key != after_atom.condition_key
                    or before_atom.principal_name_key != after_atom.principal_name_key
                    or before_atom.principal_type == after_atom.principal_type
                ):
                    continue
                replaced.append(
                    _replacement_item(before_atom, after_atom, self.high_risk)
                )
                replacement_removed.add(id(before_atom))
                replacement_added.add(id(after_atom))
                break

        remaining_removed = [
            atom for atom in sorted_removed if id(atom) not in replacement_removed
        ]
        remaining_added = [
            atom for atom in sorted_added if id(atom) not in replacement_added
        ]

        changed_pairs, remaining_removed, remaining_added = _pair_modified(
            remaining_removed, remaining_added
        )
        changed = [
            _changed_item(before_atom, after_atom, self.high_risk)
            for before_atom, after_atom in changed_pairs
        ]

        added = []
        for atom in remaining_added:
            item = _base_item(atom, self.high_risk)
            item["change"] = "added"
            added.append(item)

        removed = []
        for atom in remaining_removed:
            item = _base_item(atom, self.high_risk)
            item["change"] = "removed"
            removed.append(item)

        # Deny statements are diffed and reported independently from allows.
        deny_added_keys = set(after_denies) - set(before_denies)
        deny_removed_keys = set(before_denies) - set(after_denies)
        deny_added_atoms = [after_denies[key] for key in deny_added_keys]
        deny_removed_atoms = [before_denies[key] for key in deny_removed_keys]

        deny_pairs, deny_remaining_removed, deny_remaining_added = _pair_modified(
            sorted(deny_removed_atoms, key=_atom_display_key),
            sorted(deny_added_atoms, key=_atom_display_key),
        )

        denied = []
        deny_removed = []

        for before_atom, after_atom in deny_pairs:
            denied.append(
                _changed_item(
                    before_atom, after_atom, self.high_risk, change="modified"
                )
            )

        for atom in deny_remaining_added:
            item = _base_item(atom, self.high_risk)
            item["change"] = "added"
            denied.append(item)

        for atom in deny_remaining_removed:
            item = _base_item(atom, self.high_risk)
            item["change"] = "removed"
            deny_removed.append(item)

        denied.extend(deny_removed)

        # Annotate deny statements with the allow permissions they shadow, and
        # surface allows that have become ineffective without being edited.
        for item in denied:
            deny_atom = None
            for atom in after_denies.values():
                if (
                    atom.principal == item.get("principal")
                    and atom.action == item.get("action")
                    and atom.resource == item.get("resource")
                ):
                    deny_atom = atom
                    break
            if deny_atom is not None:
                item["overrides"] = _sorted_items(
                    [
                        _base_item(allow, self.high_risk)
                        for allow in after_allows.values()
                        if _deny_overrides(deny_atom, allow)
                    ]
                )
                item["overrides_allow"] = bool(item["overrides"])

        overridden = []
        for key, allow in after_allows.items():
            denies = _overriding_denies(allow, after_denies)
            if not denies:
                continue
            item = _base_item(allow, self.high_risk)
            item["overridden_by_deny"] = True
            item["overridden"] = True
            item["overrides"] = _sorted_items(
                [_base_item(deny, self.high_risk) for deny in denies]
            )
            if key not in before_allows:
                item["change"] = "added_but_overridden"
            elif _overriding_denies(allow, before_denies):
                item["change"] = "already_overridden"
            else:
                item["change"] = "became_ineffective"
            overridden.append(item)

        # Mark effective-added allows so a reviewer can distinguish a grant
        # from a grant that is immediately neutralized by a deny.
        for item in added + changed + replaced:
            matching = None
            for atom in after_allows.values():
                if (
                    atom.principal == item.get("principal")
                    and atom.action == item.get("action")
                    and atom.resource == item.get("resource")
                ):
                    matching = atom
                    break
            if matching is not None and _overriding_denies(matching, after_denies):
                item["overridden_by_deny"] = True
                item["effective"] = False

        unknown = []
        for atom in after_atoms.values():
            if not atom.unknown:
                continue
            item = _base_item(atom, self.high_risk)
            item["change"] = "requires_confirmation"
            item["requires_confirmation"] = True
            unknown.append(item)

        narrowed = [
            item for item in changed if item.get("direction") == "narrowed"
        ]
        widened = [
            item for item in changed if item.get("direction") == "widened"
        ]

        high_risk_items = []
        for collection in (added, removed, changed, replaced, denied):
            high_risk_items.extend(
                item for item in collection if item.get("high_risk")
            )

        before_effective = _effective_count(before_allows, before_denies)
        after_effective = _effective_count(after_allows, after_denies)
        before_allow_count = sum(1 for _ in before_allows.values())
        after_allow_count = sum(1 for _ in after_allows.values())

        counts = {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "replaced": len(replaced),
            "denied": len(denied),
            "deny_removed": len(deny_removed),
            "overridden": len(overridden),
            "narrowed": len(narrowed),
            "widened": len(widened),
            "unknown": len(unknown),
            "high_risk": len(_dedupe_items(high_risk_items)),
            "allow_before": before_allow_count,
            "allow_after": after_allow_count,
            "deny_before": len(before_denies),
            "deny_after": len(after_denies),
            "effective_before": before_effective,
            "effective_after": after_effective,
        }

        version_changed = before_version != after_version and (
            before_version is not None or after_version is not None
        )
        return {
            "version_note": _version_note(before_version, after_version),
            "version_changed": version_changed,
            "implicit_version_change": version_changed,
            "before_version": before_version,
            "after_version": after_version,
            "added": _sorted_items(added),
            "removed": _sorted_items(removed),
            "changed": _sorted_items(changed),
            "replaced": _sorted_items(replaced),
            "denied": _sorted_items(denied),
            "deny_removed": _sorted_items(deny_removed),
            "overridden": _sorted_items(overridden),
            "narrowed": _sorted_items(narrowed),
            "widened": _sorted_items(widened),
            "unknown": _sorted_items(unknown),
            "high_risk": _sorted_items(_dedupe_items(high_risk_items)),
            "counts": counts,
        }
