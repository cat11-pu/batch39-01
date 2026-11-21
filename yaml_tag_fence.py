import copy
import re

import yaml
from yaml.events import (
    AliasEvent,
    DocumentEndEvent,
    DocumentStartEvent,
    MappingEndEvent,
    MappingStartEvent,
    ScalarEvent,
    SequenceEndEvent,
    SequenceStartEvent,
    StreamEndEvent,
)

MISSING = object()

_YAML_TAG_PREFIX = "tag:yaml.org,2002:"
_CONSTRUCT_TAGS = frozenset({"str", "int", "float", "bool", "null", "seq", "map"})
_RAW_TEXT_TAGS = frozenset({"timestamp", "binary"})

_NULL_RE = re.compile(r"^(?:~|null|Null|NULL)?$")
_BOOL_RE = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")
_INT_RE = re.compile(r"^[-+]?(?:0x[0-9a-fA-F]+|0o[0-7]+|[0-9]+)$")
_FLOAT_RE = re.compile(
    r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?"
    r"|[-+]?\.(?:inf|Inf|INF)"
    r"|\.(?:nan|NaN|NAN))$"
)


class YamlTagError(ValueError):
    def __init__(self, code, line=None, column=None, anchor=None):
        super().__init__(code)
        self.code = code
        self.line = line
        self.column = column
        self.anchor = anchor


def _mark(ev):
    mark = getattr(ev, "start_mark", None)
    if mark is None:
        return None, None
    return mark.line + 1, mark.column + 1


class YamlTagFence:
    def __init__(self, max_depth=20, max_nodes=1000, max_scalar=10000, allow_merge=False):
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_scalar = max_scalar
        self.allow_merge = allow_merge

    def convert(self, text):
        docs = []
        try:
            stream = iter(yaml.parse(text))
            for ev in stream:
                if isinstance(ev, DocumentStartEvent):
                    anchors = {}
                    counter = [0]
                    first = next(stream)
                    if isinstance(first, DocumentEndEvent):
                        docs.append(None)
                    else:
                        docs.append(self._node(first, stream, 0, anchors, counter))
                elif isinstance(ev, StreamEndEvent):
                    break
        except YamlTagError:
            raise
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark is not None else None
            column = mark.column + 1 if mark is not None else None
            raise YamlTagError("parse_error", line=line, column=column) from exc
        return docs

    def events(self, text):
        try:
            for ev in yaml.parse(text):
                if isinstance(ev, DocumentStartEvent):
                    yield ("document_start",)
                elif isinstance(ev, DocumentEndEvent):
                    yield ("document_end",)
                elif isinstance(ev, ScalarEvent):
                    yield ("scalar", ev.value)
                elif isinstance(ev, SequenceStartEvent):
                    yield ("sequence_start",)
                elif isinstance(ev, SequenceEndEvent):
                    yield ("sequence_end",)
                elif isinstance(ev, MappingStartEvent):
                    yield ("mapping_start",)
                elif isinstance(ev, MappingEndEvent):
                    yield ("mapping_end",)
                elif isinstance(ev, AliasEvent):
                    yield ("alias", ev.anchor)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark is not None else None
            column = mark.column + 1 if mark is not None else None
            raise YamlTagError("parse_error", line=line, column=column) from exc

    def _count(self, counter, ev):
        counter[0] += 1
        if counter[0] > self.max_nodes:
            line, column = _mark(ev)
            raise YamlTagError("node_limit", line=line, column=column)

    def _tag_suffix(self, tag, ev):
        if tag is None:
            return None
        if tag.startswith(_YAML_TAG_PREFIX):
            suffix = tag[len(_YAML_TAG_PREFIX):]
            if suffix in _CONSTRUCT_TAGS or suffix in _RAW_TEXT_TAGS:
                return suffix
        line, column = _mark(ev)
        raise YamlTagError("unsupported_tag", line=line, column=column)

    def _scalar(self, ev):
        line, column = _mark(ev)
        if len(ev.value) > self.max_scalar:
            raise YamlTagError("scalar_limit", line=line, column=column)
        suffix = self._tag_suffix(ev.tag, ev)
        value = ev.value
        if suffix is not None:
            if suffix in _RAW_TEXT_TAGS or suffix == "str":
                return value
            if suffix == "null":
                return None
            if suffix == "bool":
                return value.lower() in ("true", "yes", "on")
            if suffix == "int":
                return int(value, 0)
            if suffix == "float":
                return float(value)
        if ev.style is not None:
            return value
        if _NULL_RE.match(value):
            return None
        if _BOOL_RE.match(value):
            return value.lower() == "true"
        if _INT_RE.match(value):
            return int(value, 0)
        if _FLOAT_RE.match(value):
            try:
                return float(value)
            except ValueError:
                return value
        return value

    def _node(self, ev, stream, depth, anchors, counter):
        line, column = _mark(ev)
        if isinstance(ev, AliasEvent):
            name = ev.anchor
            info = anchors.get(name)
            if info is None:
                raise YamlTagError("unknown_anchor", line=line, column=column, anchor=name)
            if info[2]:
                raise YamlTagError("anchor_cycle", line=line, column=column, anchor=name)
            counter[0] += info[1]
            if counter[0] > self.max_nodes:
                raise YamlTagError("node_limit", line=line, column=column, anchor=name)
            return copy.deepcopy(info[0])
        if isinstance(ev, ScalarEvent):
            self._count(counter, ev)
            value = self._scalar(ev)
            if ev.anchor:
                anchors[ev.anchor] = [value, 1, False]
            return value
        if isinstance(ev, (SequenceStartEvent, MappingStartEvent)):
            self._tag_suffix(ev.tag, ev)
            if depth + 1 > self.max_depth:
                raise YamlTagError("depth_limit", line=line, column=column)
            self._count(counter, ev)
            anchor = ev.anchor
            if anchor:
                anchors[anchor] = [None, 0, True]
            before = counter[0]
            if isinstance(ev, SequenceStartEvent):
                result = []
                for child in stream:
                    if isinstance(child, SequenceEndEvent):
                        break
                    result.append(self._node(child, stream, depth + 1, anchors, counter))
            else:
                result = {}
                while True:
                    key_ev = next(stream)
                    if isinstance(key_ev, MappingEndEvent):
                        break
                    key = self._node(key_ev, stream, depth + 1, anchors, counter)
                    if key == "<<" and not self.allow_merge:
                        kline, kcol = _mark(key_ev)
                        raise YamlTagError("merge_key", line=kline, column=kcol)
                    try:
                        duplicated = key in result
                    except TypeError:
                        kline, kcol = _mark(key_ev)
                        raise YamlTagError("unhashable_key", line=kline, column=kcol)
                    if duplicated:
                        kline, kcol = _mark(key_ev)
                        raise YamlTagError("duplicate_key", line=kline, column=kcol)
                    value_ev = next(stream)
                    result[key] = self._node(value_ev, stream, depth + 1, anchors, counter)
            if anchor:
                anchors[anchor] = [result, counter[0] - before + 1, False]
            return result
        line, column = _mark(ev)
        raise YamlTagError("parse_error", line=line, column=column)
