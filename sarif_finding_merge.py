import hashlib
import json
import posixpath
import re
from urllib.parse import unquote, urlsplit


_DEFAULT_OVERLAP = object()
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")

_SEVERITY_LEVELS = {
    "critical": 3,
    "high": 2,
    "medium": 1,
    "low": 0,
}

_SEVERITY_MAP = {
    "critical": "critical",
    "blocker": "critical",
    "severe": "critical",
    "严重": "critical",
    "阻断": "critical",
    "error": "high",
    "high": "high",
    "fatal": "high",
    "高危": "high",
    "错误": "high",
    "致命": "high",
    "warning": "medium",
    "warn": "medium",
    "medium": "medium",
    "moderate": "medium",
    "中危": "medium",
    "警告": "medium",
    "note": "low",
    "low": "low",
    "info": "low",
    "information": "low",
    "informational": "low",
    "提示": "low",
    "低危": "low",
}


class SarifFindingMerge:
    def __init__(self, workdir=None, case_sensitive=False, overlap=_DEFAULT_OVERLAP):
        self.case_sensitive = bool(case_sensitive)
        self._overlap_explicit = overlap is not _DEFAULT_OVERLAP
        self.overlap = 0.5 if overlap is _DEFAULT_OVERLAP else float(overlap)
        self.workdir = self._canonical_path(workdir) if workdir not in (None, "") else None

    def merge(self, reports, baseline=None):
        records = []
        warnings = set()

        for report in self._iter_reports(reports):
            artifacts = report.get("artifacts", [])
            findings = report.get("findings", [])
            if findings is None:
                findings = []
            for raw in findings:
                record = self._normalize_finding(raw, artifacts, warnings)
                records.append(record)

        groups = self._group_records(records)
        findings = []
        suppressed = []

        for group in groups:
            item = self._merge_group(group)
            item["suppressed"] = bool(item["suppressed"])
            if item["suppressed"]:
                suppressed.append(item)
            else:
                findings.append(item)

        findings.sort(key=self._sort_key)
        suppressed.sort(key=self._sort_key)

        baseline_fingerprints = self._baseline_fingerprints(baseline)
        new = [item for item in findings if item["fingerprint"] not in baseline_fingerprints]
        active_fingerprints = {item["fingerprint"] for item in new}
        active_fingerprints.update(item["fingerprint"] for item in suppressed)
        fixed = sorted(baseline_fingerprints - active_fingerprints)

        return {
            "findings": findings,
            "suppressed": suppressed,
            "new": new,
            "fixed": fixed,
            "warnings": sorted(warnings),
        }

    def _iter_reports(self, reports):
        if reports is None:
            return
        if isinstance(reports, dict):
            if "runs" in reports:
                for run in reports.get("runs") or []:
                    if not isinstance(run, dict):
                        continue
                    artifacts = run.get(
                        "artifacts", run.get("artifactLocations", [])
                    )
                    findings = run.get("findings")
                    if findings is None:
                        findings = run.get("results", [])
                    yield {
                        "artifacts": artifacts or [],
                        "findings": findings or [],
                    }
                return
            artifacts = reports.get("artifacts", reports.get("artifactLocations", []))
            findings = reports.get("findings")
            if findings is None:
                findings = reports.get("results", [])
            yield {"artifacts": artifacts or [], "findings": findings or []}
            return
        if isinstance(reports, (list, tuple)):
            for report in reports:
                yield from self._iter_reports(report)
            return
        yield {"artifacts": [], "findings": list(reports)}

    def _normalize_finding(self, raw, artifacts, warnings):
        item = dict(raw) if isinstance(raw, dict) else {"message": str(raw)}
        location, region = self._location_parts(item)
        _, artifact_location = self._physical_parts(item, location)

        raw_artifact_index = self._first(
            item, "artifact_index", "artifactIndex", "artifact_index_", default=None
        )
        if raw_artifact_index is None:
            raw_artifact_index = self._first(
                artifact_location, "index", "artifactIndex", default=None
            )
        artifact_index, artifact_path = self._resolve_artifact(
            raw_artifact_index,
            artifacts,
            warnings,
        )

        raw_path = self._first(
            item,
            "path",
            "file",
            "uri",
            "file_path",
            "fileName",
            default=None,
        )
        if not raw_path:
            raw_path = self._first(
                location,
                "path",
                "uri",
                "file",
                default=None,
            )
        if not raw_path:
            raw_path = self._first(
                artifact_location,
                "uri",
                "path",
                "file",
                default=None,
            )
        if not raw_path and artifact_path:
            raw_path = artifact_path

        path = self._normalize_report_path(raw_path)
        rule = self._normalize_rule(
            self._first(item, "rule", "ruleId", "rule_id", default="")
        )
        line = self._as_int(
            self._first(region, "startLine", "line", "start_line", default=item.get("line", 1)),
            1,
        )
        column = self._as_int(
            self._first(
                region,
                "startColumn",
                "column",
                "start_column",
                default=item.get("column", 1),
            ),
            1,
        )
        end_line = self._as_int(
            self._first(
                region,
                "endLine",
                "end_line",
                default=item.get("endLine", item.get("end_line", line)),
            ),
            line,
        )
        end_column = self._as_int(
            self._first(
                region,
                "endColumn",
                "end_column",
                default=item.get("endColumn", item.get("end_column", column)),
            ),
            column,
        )
        if line == 0:
            end_line = 0
            end_column = 0
        if end_line < line:
            end_line = line
        if end_line == line and end_column < column:
            end_column = column

        severity_raw, severity, unmapped = self._normalize_severity(
            self._first(item, "severity", "level", "severity_level", default="")
        )
        message = self._normalize_message(
            self._first(item, "message", "description", default="")
        )
        signature = self._provided_fingerprint(
            self._first(
                item,
                "fingerprint",
                "fingerprints",
                "partialFingerprints",
                default=None,
            )
        )
        complete = self._is_complete_fingerprint(signature)
        fingerprint = (
            signature
            if complete
            else self._derived_fingerprint(
                rule, path, line, column, end_line, end_column, message
            )
        )
        suppressed = self._is_suppressed(item)

        return {
            "raw": item,
            "path": path,
            "path_key": self._path_key(path),
            "rule": rule,
            "line": line,
            "column": column,
            "end_line": end_line,
            "end_column": end_column,
            "has_span": end_line > line or end_column > column,
            "whole_file": line == 0,
            "severity": severity,
            "severity_raw": severity_raw,
            "severity_unmapped": unmapped,
            "message": message,
            "fingerprint": fingerprint,
            "provided_fingerprint": signature,
            "fingerprint_complete": complete,
            "suppressed": suppressed,
            "artifact_index": artifact_index,
            "artifact": artifact_path,
        }

    def _location_parts(self, item):
        location = item.get("location")
        if not isinstance(location, dict):
            locations = item.get("locations")
            location = locations[0] if isinstance(locations, list) and locations else {}
        location = location if isinstance(location, dict) else {}

        physical = location.get("physicalLocation")
        if not isinstance(physical, dict):
            physical = item.get("physicalLocation")
        physical = physical if isinstance(physical, dict) else {}

        region = physical.get("region")
        if not isinstance(region, dict):
            region = location.get("region")
        region = region if isinstance(region, dict) else {}
        return location, region

    def _physical_parts(self, item, location):
        physical = location.get("physicalLocation")
        if not isinstance(physical, dict):
            physical = item.get("physicalLocation")
        physical = physical if isinstance(physical, dict) else {}
        artifact_location = physical.get("artifactLocation")
        if not isinstance(artifact_location, dict):
            artifact_location = location.get("artifactLocation")
        artifact_location = (
            artifact_location if isinstance(artifact_location, dict) else {}
        )
        return physical, artifact_location

    def _resolve_artifact(self, raw_index, artifacts, warnings):
        if raw_index in (None, ""):
            return None, None
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            warnings.add("artifact_missing")
            return raw_index, None
        if index < 0 or index >= len(artifacts):
            warnings.add("artifact_missing")
            return index, None
        path = self._artifact_path(artifacts[index])
        if not path:
            warnings.add("artifact_missing")
            return index, None
        return index, self._normalize_report_path(path)

    def _artifact_path(self, artifact):
        if isinstance(artifact, str):
            return artifact
        if not isinstance(artifact, dict):
            return None
        location = artifact.get("location")
        if isinstance(location, dict):
            path = location.get("uri", location.get("path"))
            if path:
                return path
        return self._first(
            artifact,
            "uri",
            "path",
            "file",
            "fileName",
            default=None,
        )

    def _normalize_report_path(self, raw_path):
        path = self._canonical_path(raw_path)
        if not path or not self.workdir:
            return path
        workdir = self.workdir.rstrip("/")
        if not workdir:
            return path
        if self.case_sensitive:
            path_cmp = path
            workdir_cmp = workdir
        else:
            path_cmp = path.casefold()
            workdir_cmp = workdir.casefold()
        if path_cmp == workdir_cmp:
            return ""
        if path_cmp.startswith(workdir_cmp + "/"):
            return path[len(workdir):].lstrip("/")
        return path

    def _canonical_path(self, value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        path = str(value).strip()
        if len(path) >= 2 and path[0] == path[-1] and path[0] in ("'", '"'):
            path = path[1:-1]
        if not path:
            return ""

        path = unquote(path)
        if path.lower().startswith("file:"):
            parts = urlsplit(path)
            netloc = unquote(parts.netloc)
            path = unquote(parts.path)
            if netloc and _WINDOWS_DRIVE_RE.match(netloc):
                path = netloc + path
            elif netloc and netloc.lower() != "localhost":
                path = "//" + netloc + path

        path = path.replace("\\", "/")
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        if not path:
            return ""
        path = posixpath.normpath(path)
        if path == ".":
            return ""
        return path

    def _path_key(self, path):
        return path if self.case_sensitive else path.casefold()

    def _normalize_rule(self, value):
        if isinstance(value, dict):
            value = self._first(value, "id", "ruleId", "rule_id", default="")
        return str(value or "").strip().lower()

    def _normalize_severity(self, value):
        raw = str(value or "").strip()
        normalized = _SEVERITY_MAP.get(raw.lower())
        if normalized is None:
            return raw, "low", True
        return raw, normalized, False

    def _normalize_message(self, value):
        if isinstance(value, dict):
            value = self._first(value, "text", "markdown", "message", default="")
        text = str(value or "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\n\t\f\v]+", " ", text)
        text = re.sub(r" +", " ", text)
        return text.strip()

    def _provided_fingerprint(self, value):
        if isinstance(value, dict):
            for key in ("value", "fingerprint", "primaryLocationLineHash"):
                if key in value:
                    return self._provided_fingerprint(value[key])
            if not value:
                return ""
            return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, (list, tuple)):
            if not value:
                return ""
            return json.dumps(list(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return str(value or "").strip()

    def _is_complete_fingerprint(self, fingerprint):
        return bool(fingerprint) and len(fingerprint) >= 4

    def _derived_fingerprint(
        self, rule, path, line, column, end_line, end_column, message
    ):
        parts = [
            rule,
            self._path_key(path),
            str(line),
            str(column),
            str(end_line),
            str(end_column),
            hashlib.sha256(message.encode("utf-8")).hexdigest(),
        ]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def _is_suppressed(self, item):
        value = self._first(item, "suppressed", "isSuppressed", default=None)
        if value is None:
            suppressions = item.get("suppressions")
            if isinstance(suppressions, list):
                return len(suppressions) > 0
            return False
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "no", "none")
        return bool(value)

    def _group_records(self, records):
        parent = list(range(len(records)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left in range(len(records)):
            for right in range(left + 1, len(records)):
                if self._records_match(records[left], records[right]):
                    union(left, right)

        groups = {}
        for index, record in enumerate(records):
            groups.setdefault(find(index), []).append(record)
        return [groups[key] for key in sorted(groups)]

    def _records_match(self, left, right):
        if left["path_key"] != right["path_key"]:
            return False
        if left["rule"] != right["rule"]:
            return False
        if left["severity"] != right["severity"]:
            return False
        if left["whole_file"] or right["whole_file"]:
            return left["whole_file"] and right["whole_file"]

        left_complete = left["fingerprint_complete"]
        right_complete = right["fingerprint_complete"]

        if left_complete and right_complete:
            if left["provided_fingerprint"] != right["provided_fingerprint"]:
                return False
            if self._regions_overlap(left, right):
                return True
            return self._fuzzy_points_match(left, right)

        if not left_complete and not right_complete:
            return left["fingerprint"] == right["fingerprint"]

        if left_complete or right_complete:
            return self._anchor_match(left, right)

        return False

    def _anchor_match(self, left, right):
        return (
            left["line"] == right["line"]
            and left["column"] == right["column"]
            and left["end_line"] == right["end_line"]
            and left["end_column"] == right["end_column"]
            and left["message"] == right["message"]
        )

    def _regions_overlap(self, left, right):
        if not left["has_span"] and not right["has_span"]:
            return left["line"] == right["line"] and left["column"] == right["column"]

        left_start = left["line"] * 1_000_000 + left["column"]
        left_end = left["end_line"] * 1_000_000 + left["end_column"] + 1
        right_start = right["line"] * 1_000_000 + right["column"]
        right_end = right["end_line"] * 1_000_000 + right["end_column"] + 1

        overlap = min(left_end, right_end) - max(left_start, right_start)
        if overlap <= 0:
            return False
        shortest = min(left_end - left_start, right_end - right_start)
        return shortest > 0 and (overlap / shortest) > self.overlap

    def _fuzzy_points_match(self, left, right):
        return (
            self._overlap_explicit
            and self.overlap <= 0.5
            and not left["has_span"]
            and not right["has_span"]
            and left["line"] == right["line"]
            and left["column"] != right["column"]
        )

    def _merge_group(self, group):
        group = sorted(group, key=self._record_sort_key)
        paths = sorted({record["path"] for record in group}, key=lambda p: (p.casefold(), p))
        path = paths[0] if paths else ""
        rule = group[0]["rule"]
        line = min(record["line"] for record in group)
        column = min(
            record["column"] for record in group if record["line"] == line
        )
        end_line = max(record["end_line"] for record in group)
        end_column = max(record["end_column"] for record in group)
        whole_file = any(record["whole_file"] for record in group)

        severity = max(
            (record["severity"] for record in group),
            key=lambda level: _SEVERITY_LEVELS.get(level, 0),
        )
        messages = [record["message"] for record in group if record["message"]]
        message = min(messages, key=lambda text: (text.casefold(), text)) if messages else ""

        complete = [
            record["provided_fingerprint"]
            for record in group
            if record["fingerprint_complete"]
        ]
        fingerprint = min(complete) if complete else group[0]["fingerprint"]
        artifact_indexes = [
            record["artifact_index"]
            for record in group
            if record["artifact_index"] is not None
        ]
        artifact_index = (
            min(
                artifact_indexes,
                key=lambda value: (
                    (0, value)
                    if isinstance(value, int)
                    else (1, str(value))
                ),
            )
            if artifact_indexes
            else None
        )

        base = dict(group[0]["raw"])
        base.update(
            {
                "path": path,
                "rule": rule,
                "line": line,
                "column": column,
                "severity": severity,
                "message": message,
                "fingerprint": fingerprint,
                "suppressed": any(record["suppressed"] for record in group),
                "whole_file": whole_file,
            }
        )
        if any(record["has_span"] for record in group):
            base["endLine"] = end_line
            base["endColumn"] = end_column
        if artifact_index is not None:
            base["artifact_index"] = artifact_index
        if whole_file:
            base["line_zero"] = True

        unmapped = [record for record in group if record["severity_unmapped"]]
        if unmapped:
            original_severity = min(
                (record["severity_raw"] for record in unmapped),
                key=lambda value: (value.casefold(), value),
            )
            base["severity_unmapped"] = True
            base["severity_unknown"] = True
            base["unknown_severity"] = True
            base["severity_original"] = original_severity
            base["severity_raw"] = original_severity
            base["original_severity"] = original_severity
        return base

    def _sort_key(self, item):
        return (
            self._path_key(item["path"]),
            item["line"],
            item["column"],
            item["rule"],
            item["fingerprint"],
            item["message"],
        )

    def _record_sort_key(self, record):
        artifact_index = record["artifact_index"]
        return (
            self._sort_key(record),
            record["severity_raw"],
            record["severity_unmapped"],
            record["fingerprint_complete"],
            record["provided_fingerprint"],
            artifact_index is not None,
            str(artifact_index),
            json.dumps(
                record["raw"],
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ),
        )

    def _baseline_fingerprints(self, baseline):
        if baseline is None:
            return set()
        if isinstance(baseline, dict):
            for key in ("fingerprints", "findings", "items", "results"):
                if key in baseline:
                    return self._baseline_fingerprints(baseline[key])
            value = self._provided_fingerprint(
                self._first(
                    baseline,
                    "fingerprint",
                    "fingerprints",
                    "partialFingerprints",
                    default=None,
                )
            )
            if value:
                return {value}
            return set(str(key) for key in baseline)
        if isinstance(baseline, str):
            return {baseline}
        result = set()
        for item in baseline:
            if isinstance(item, dict):
                value = self._first(
                    item,
                    "fingerprint",
                    "fingerprints",
                    "partialFingerprints",
                    default=None,
                )
                value = self._provided_fingerprint(value)
                if value:
                    result.add(value)
            elif item is not None:
                result.add(str(item))
        return result

    def _first(self, mapping, *keys, default=None):
        if not isinstance(mapping, dict):
            return default
        for key in keys:
            if key in mapping and mapping[key] is not None:
                return mapping[key]
        return default

    def _as_int(self, value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
