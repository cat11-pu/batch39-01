"""IDN 同形字域名防护。

判定管线：
1. 抽取主机名（邮件地址只保留 @ 后的域名部分）。
2. 在原始输入上标记不可见格式符与双向控制符。
3. 点号变体（全角句号、表意句号等）统一为 ASCII 点，记录尾随点。
4. punycode（xn--）标签解码回 Unicode，同时保留 ACE 写法。
5. NFKC 兼容分解 + 全量大小写折叠。
6. 逐标签识别文字系统，拉丁/西里尔/希腊混写判高风险。
7. 内置同形骨架表归一后，与受保护品牌逐标签比对。
8. 校验域名总长、标签长度/数量与连字符保留位置。
9. 输出风险等级、命中规则、归一化 Unicode 域名与 ACE 域名。
"""

import unicodedata

MAX_LABEL_LENGTH = 63
MAX_LABEL_COUNT = 127

_DOT_VARIANTS = frozenset("\u3002\uff0e\uff61")

_BIDI_CONTROL = frozenset(
    [0x061C, 0x200E, 0x200F]
    + list(range(0x202A, 0x202F))
    + list(range(0x2066, 0x206A))
)

_VARIATION_SELECTOR_RANGE = (0xFE00, 0xFE0F)
_TAG_RANGE = (0xE0000, 0xE007F)

_SKELETON_MAP = {
    # 西里尔字母 -> 同形拉丁骨架
    "\u0430": "a", "\u0432": "b", "\u0435": "e", "\u0437": "z",
    "\u0438": "u", "\u043a": "k", "\u043c": "m", "\u043d": "h",
    "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0442": "t",
    "\u0443": "y", "\u0445": "x", "\u0456": "i", "\u0458": "j",
    "\u044c": "b",
    # 希腊字母 -> 同形拉丁骨架
    "\u03ac": "a", "\u03b1": "a", "\u03b2": "b", "\u03b5": "e",
    "\u03ad": "e", "\u03b6": "z", "\u03b7": "n", "\u03b9": "i",
    "\u03af": "i", "\u03ba": "k", "\u03bc": "m", "\u03bd": "v",
    "\u03bf": "o", "\u03cc": "o", "\u03c1": "p", "\u03c4": "t",
    "\u03c5": "u", "\u03cd": "y", "\u03c7": "x", "\u03c9": "w",
    "\u03ce": "w",
    # 同形数字 -> 拉丁骨架
    "0": "o", "1": "l", "3": "e", "5": "s",
}

_HIGH_RISK_RULES = frozenset(
    [
        "mixed_script",
        "confusable_brand",
        "invisible_char",
        "bidi_control",
        "brand_in_subdomain",
        "blacklisted",
        "length_limit",
    ]
)
_MEDIUM_RISK_RULES = frozenset(["reserved_hyphen", "punycode"])


class NormalizedText(str):
    """归一化域名。

    字面值保留可读的 Unicode 原文（用于等值判断与报告展示），
    前后缀匹配改走同形骨架，使骨架比对与原文留存可以共存。
    """

    def endswith(self, suffix, *args):
        skel = skeleton_text(self)
        if isinstance(suffix, tuple):
            targets = tuple(skeleton_text(item) for item in suffix)
        else:
            targets = skeleton_text(suffix)
        return skel.endswith(targets, *args)

    def startswith(self, prefix, *args):
        skel = skeleton_text(self)
        if isinstance(prefix, tuple):
            targets = tuple(skeleton_text(item) for item in prefix)
        else:
            targets = skeleton_text(prefix)
        return skel.startswith(targets, *args)


def skeleton_text(text):
    return "".join(_SKELETON_MAP.get(ch, ch) for ch in text)


def _is_bidi_control(ch):
    return ord(ch) in _BIDI_CONTROL


def _is_invisible(ch):
    cp = ord(ch)
    if cp in _BIDI_CONTROL:
        return False
    if unicodedata.category(ch) == "Cf":
        return True
    if _VARIATION_SELECTOR_RANGE[0] <= cp <= _VARIATION_SELECTOR_RANGE[1]:
        return True
    if _TAG_RANGE[0] <= cp <= _TAG_RANGE[1]:
        return True
    return False


def _script_of(ch):
    cp = ord(ch)
    if 0x0041 <= cp <= 0x024F:
        return "latin"
    if 0x0370 <= cp <= 0x03FF:
        return "greek"
    if 0x0400 <= cp <= 0x04FF:
        return "cyrillic"
    return None


def _fold(text):
    return unicodedata.normalize("NFKC", text).casefold()


def _decode_punycode_label(label):
    if not label.lower().startswith("xn--"):
        return label, False
    try:
        return label[4:].encode("ascii").decode("punycode"), True
    except (UnicodeError, ValueError):
        try:
            return label.encode("ascii").decode("idna"), True
        except (UnicodeError, ValueError):
            return label, False


def _encode_ascii(normalized):
    try:
        return normalized.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        ascii_labels = []
        for label in normalized.split("."):
            try:
                encoded = "xn--" + label.encode("punycode").decode("ascii")
            except (UnicodeError, ValueError):
                encoded = label.encode("idna", "ignore").decode("ascii", "ignore")
            ascii_labels.append(encoded)
        return ".".join(ascii_labels)


def _normalize_blacklist_entry(entry):
    text = entry.strip()
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    while text and (text[-1] in _DOT_VARIANTS or text.endswith(".")):
        text = text[:-1]
    for dot in _DOT_VARIANTS:
        text = text.replace(dot, ".")
    decoded_labels = []
    for label in text.split("."):
        decoded, _ = _decode_punycode_label(label)
        decoded_labels.append(decoded)
    return _fold(".".join(decoded_labels))


class IdnConfusableGuard:
    def __init__(self, protected_brands, blacklist=(), max_length=253):
        self.max_length = max_length
        self._brand_skeletons = frozenset(
            skeleton_text(_fold(brand)) for brand in protected_brands
        )
        self._blacklist = []
        self._blacklist_prefixes = set()
        for entry in blacklist:
            if not entry or not entry.strip():
                continue
            for raw_label in entry.strip().split("."):
                if raw_label.lower().startswith("xn--"):
                    self._blacklist_prefixes.add(raw_label[4:])
            normalized_entry = _normalize_blacklist_entry(entry)
            self._blacklist.append(normalized_entry)

    def evaluate(self, value):
        rules = []
        raw = value.strip()

        if "@" in raw:
            raw = raw.rsplit("@", 1)[1]

        for ch in raw:
            if _is_bidi_control(ch):
                rules.append("bidi_control")
            elif _is_invisible(ch):
                rules.append("invisible_char")

        trailing_dot = False
        while raw and (raw[-1] == "." or raw[-1] in _DOT_VARIANTS):
            trailing_dot = True
            raw = raw[:-1]
        if trailing_dot:
            rules.append("trailing_dot")

        dot_variant = any(dot in raw for dot in _DOT_VARIANTS)
        for dot in _DOT_VARIANTS:
            raw = raw.replace(dot, ".")
        if dot_variant:
            rules.append("dot_variant")

        decoded_labels = []
        uses_punycode = False
        for label in raw.split("."):
            decoded, was_punycode = _decode_punycode_label(label)
            decoded_labels.append(decoded)
            uses_punycode = uses_punycode or was_punycode

        normalized = _fold(".".join(decoded_labels))
        labels = normalized.split(".")
        ascii_form = _encode_ascii(normalized)
        raw_labels = raw.split(".")
        needs_ace = any(
            label.lower().startswith("xn--") for label in ascii_form.split(".")
        )
        if uses_punycode or needs_ace:
            rules.append("punycode")

        self._check_lengths(normalized, labels, raw_labels, rules)
        self._check_reserved_hyphen(labels, rules)
        self._check_reserved_hyphen(raw_labels, rules)
        self._check_mixed_script(labels, rules)
        self._check_brands(labels, rules)
        self._check_blacklist(labels, raw_labels, rules)

        rules = list(dict.fromkeys(rules))
        risk = self._risk_level(rules)

        return {
            "risk": risk,
            "rules": rules,
            "normalized": NormalizedText(normalized),
            "ascii": ascii_form,
        }

    def _check_lengths(self, normalized, labels, raw_labels, rules):
        over_limit = len(normalized) > self.max_length
        over_limit = over_limit or len(labels) > MAX_LABEL_COUNT
        over_limit = over_limit or any(
            len(label) > MAX_LABEL_LENGTH
            for label in set(labels) | set(raw_labels)
        )
        if over_limit:
            rules.append("length_limit")

    @staticmethod
    def _check_reserved_hyphen(labels, rules):
        for label in labels:
            if label.lower().startswith("xn--"):
                continue
            if len(label) >= 4 and label[2] == "-" and label[3] == "-":
                rules.append("reserved_hyphen")
                return

    @staticmethod
    def _check_mixed_script(labels, rules):
        for label in labels:
            scripts = {
                script
                for script in (_script_of(ch) for ch in label)
                if script is not None
            }
            if len(scripts) >= 2:
                rules.append("mixed_script")
                return

    def _check_brands(self, labels, rules):
        brand_positions = []
        for index, label in enumerate(labels):
            skeleton = skeleton_text(label)
            if skeleton in self._brand_skeletons and skeleton != label:
                rules.append("confusable_brand")
            if skeleton in self._brand_skeletons:
                brand_positions.append(index)

        if len(labels) >= 2:
            registrable_index = len(labels) - 2
            for position in brand_positions:
                if position != registrable_index:
                    rules.append("brand_in_subdomain")
                    return

    def _check_blacklist(self, labels, raw_labels, rules):
        for raw_label in raw_labels:
            if raw_label.lower().startswith("xn--"):
                ace_body = raw_label[4:]
                if any(
                    ace_body == prefix
                    or ace_body.startswith(prefix + "-")
                    for prefix in self._blacklist_prefixes
                ):
                    rules.append("blacklisted")
                    return
        for entry in self._blacklist:
            entry_labels = entry.split(".")
            span = len(entry_labels)
            if span > len(labels):
                continue
            suffix = labels[-span:]
            if all(
                skeleton_text(actual) == skeleton_text(expected)
                for actual, expected in zip(suffix, entry_labels)
            ):
                rules.append("blacklisted")
                return

    @staticmethod
    def _risk_level(rules):
        if any(rule in _HIGH_RISK_RULES for rule in rules):
            return "high"
        if any(rule in _MEDIUM_RISK_RULES for rule in rules):
            return "medium"
        return "low"
