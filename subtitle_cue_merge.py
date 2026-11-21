import re


CJK_LO, CJK_HI = 0x4E00, 0x9FFF
BREAK_PUNCTUATION = "，。！？；：、…,.!?;:"
DEFAULT_MAX_CHARS = {"zh": 20, "en": 42}
DEFAULT_CPS = {"zh": 15, "en": 20}

SPEAKER_TAG_RE = re.compile(r"^([\w一-鿿·\-]{1,12})\s*[：:]\s*(.+)$")


def _is_cjk(ch):
    return CJK_LO <= ord(ch) <= CJK_HI


def _detect_language(text):
    for ch in text:
        if _is_cjk(ch):
            return "zh"
    return "en"


def _wrap_line(line, limit):
    parts = []
    current = ""
    punct_pos = -1
    for ch in line:
        current += ch
        if ch in BREAK_PUNCTUATION:
            punct_pos = len(current)
        if len(current) >= limit:
            if punct_pos > 0:
                parts.append(current[:punct_pos].strip())
                current = current[punct_pos:].lstrip()
            else:
                parts.append(current)
                current = ""
            punct_pos = -1
    if current.strip():
        parts.append(current.strip())
    return "\n".join(parts)


def _wrap_text(text, limit):
    return "\n".join(_wrap_line(line, limit) for line in text.split("\n"))


class SubtitleCueMerge:
    """Normalize subtitle cues, then merge overlaps and short gaps."""

    def __init__(self, min_duration=1000, gap=100, max_chars=42, cps=15):
        self.min_duration = min_duration
        self.gap = gap
        # Accept either one scalar threshold or a per-language mapping.
        self.max_chars = max_chars
        self.cps = cps

    @staticmethod
    def _resolve(value, language, defaults):
        if isinstance(value, dict):
            return value.get(language, value.get("default", defaults[language]))
        return value

    @staticmethod
    def _frame_to_ms(frame, fps):
        # Floor consistently so frame->ms conversion never drifts over time.
        return int(frame) * 1000 // int(fps)

    def _to_milliseconds(self, cue, fps):
        if "start_frame" in cue and cue["start_frame"] is not None:
            start = self._frame_to_ms(cue["start_frame"], fps)
            end = self._frame_to_ms(cue["end_frame"], fps)
            return start, end
        return int(cue["start"]), int(cue["end"])

    @staticmethod
    def _split_speaker(text, speaker):
        text = text or ""
        if speaker is None:
            match = SPEAKER_TAG_RE.match(text.strip())
            if match:
                return match.group(2).strip(), match.group(1)
        return text, speaker

    @staticmethod
    def _warning(code, message, source_index=None):
        item = {"code": code, "message": message}
        if source_index is not None:
            item["source_index"] = source_index
        return item

    def _normalize(self, cues, fps, warnings):
        normalized = []
        seen = set()
        for seq, raw in enumerate(cues):
            cue = dict(raw)
            source_index = cue.get("index", seq)
            start, end = self._to_milliseconds(cue, fps)
            duration = end - start
            if duration == 0:
                warnings.append(self._warning(
                    "zero_duration",
                    "zero-duration cue dropped",
                    source_index,
                ))
                continue
            if duration < 0:
                warnings.append(self._warning(
                    "negative_duration",
                    "negative-duration cue dropped",
                    source_index,
                ))
                continue
            text, speaker = self._split_speaker(cue.get("text", ""), cue.get("speaker"))
            style = cue.get("style", "default")
            dedup_key = (start, end, text, style, speaker)
            if dedup_key in seen:
                warnings.append(self._warning(
                    "duplicate_import",
                    "duplicate cue ignored on re-import",
                    source_index,
                ))
                continue
            seen.add(dedup_key)
            normalized.append({
                "start": start,
                "end": end,
                "text": text,
                "style": style,
                "speaker": speaker,
                "source_index": source_index,
                "source_indices": [source_index],
                "seq": seq,
                "start_frame": cue.get("start_frame"),
                "end_frame": cue.get("end_frame"),
            })
        return normalized

    @staticmethod
    def _same_group(left, right):
        return left["style"] == right["style"] and left["speaker"] == right["speaker"]

    def _can_merge(self, previous, cue):
        if not self._same_group(previous, cue):
            return False
        return cue["start"] - previous["end"] < self.gap

    @staticmethod
    def _merge_into(target, cue):
        target["end"] = max(target["end"], cue["end"])
        target["start"] = min(target["start"], cue["start"])
        target["text"] = target["text"] + " " + cue["text"]
        target["source_indices"].extend(cue["source_indices"])
        if cue.get("start_frame") is not None:
            if target.get("start_frame") is None or cue["start_frame"] < target["start_frame"]:
                target["start_frame"] = cue["start_frame"]
        if cue.get("end_frame") is not None:
            if target.get("end_frame") is None or cue["end_frame"] > target["end_frame"]:
                target["end_frame"] = cue["end_frame"]

    def _enforce_min_duration(self, cues):
        for pos, cue in enumerate(cues):
            if cue["end"] - cue["start"] >= self.min_duration:
                continue
            desired_end = cue["start"] + self.min_duration
            if pos + 1 < len(cues):
                # Extend forward, but never intrude into the following cue.
                desired_end = min(desired_end, cues[pos + 1]["start"])
            cue["end"] = max(cue["end"], desired_end)

    def merge(self, cues, fps=25):
        warnings = []
        conflicts = []

        normalized = self._normalize(cues, fps, warnings)

        original_starts = [cue["start"] for cue in normalized]
        if original_starts != sorted(original_starts):
            warnings.append(self._warning(
                "unsorted_input",
                "cues were out of order and have been sorted before merging",
            ))

        # Stable sort: start, then end, then original input position.
        normalized.sort(key=lambda cue: (cue["start"], cue["end"], cue["seq"]))

        merged = []
        for cue in normalized:
            if merged and self._can_merge(merged[-1], cue):
                self._merge_into(merged[-1], cue)
                continue
            if merged and cue["start"] < merged[-1]["end"]:
                reason = "style" if cue["style"] != merged[-1]["style"] else "speaker"
                conflicts.append({
                    "code": "overlap_conflict",
                    "reason": reason,
                    "start": max(cue["start"], merged[-1]["start"]),
                    "end": min(cue["end"], merged[-1]["end"]),
                    "source_indices": merged[-1]["source_indices"] + cue["source_indices"],
                })
            merged.append(dict(cue))

        self._enforce_min_duration(merged)

        for cue in merged:
            language = _detect_language(cue["text"])
            char_limit = self._resolve(self.max_chars, language, DEFAULT_MAX_CHARS)
            wrapped = _wrap_text(cue["text"], char_limit)
            if wrapped != cue["text"]:
                cue["text"] = wrapped
                warnings.append(self._warning(
                    "line_wrapped",
                    "line exceeded %s character limit and was wrapped" % char_limit,
                    cue["source_index"],
                ))
            cps_limit = self._resolve(self.cps, language, DEFAULT_CPS)
            visible_chars = len("".join(cue["text"].split()))
            duration_seconds = max(cue["end"] - cue["start"], 1) / 1000
            actual_cps = visible_chars / duration_seconds
            if actual_cps > cps_limit:
                warnings.append(self._warning(
                    "reading_speed",
                    "reading speed %.1f chars/s exceeds limit %s" % (actual_cps, cps_limit),
                    cue["source_index"],
                ))
            cue.pop("seq", None)
            if cue.get("start_frame") is None:
                cue.pop("start_frame", None)
            if cue.get("end_frame") is None:
                cue.pop("end_frame", None)

        return {"cues": merged, "warnings": warnings, "conflicts": conflicts}
