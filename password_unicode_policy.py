import hashlib
import unicodedata


class PasswordError(ValueError):
    def __init__(self, code, rules=None, version=None):
        super().__init__(code)
        self.code = code
        self.rules = list(rules or [])
        self.version = version


class PasswordUnicodePolicy:
    _RESULT_RULES = (
        "nfkc_casefold",
        "character_safety",
        "grapheme_length",
        "byte_length",
        "common_password",
        "pinyin_weak",
        "sequence",
        "repeated_characters",
        "username_contained",
        "breached",
    )

    _BIDI_CONTROLS = frozenset(
        {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}
    )
    _REJECTED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Cn", "Zl", "Zp"})
    _ZWJ = "\u200d"

    _PINYIN_ROOTS = (
        "woaini",
        "woshishui",
        "buzhidao",
        "nihao",
        "wangyi",
        "zhangwei",
        "wangwei",
        "zhangsan",
        "xiaoming",
        "lihua",
        "liuyang",
        "yangyang",
        "zhongguo",
        "beijing",
        "shanghai",
        "baidu",
        "taobao",
        "weixin",
    )

    _BUILTIN_COMMON = frozenset(
        {
            "password",
            "password1",
            "password123",
            "passw0rd",
            "letmein",
            "welcome",
            "welcome1",
            "admin",
            "admin123",
            "iloveyou",
            "monkey",
            "dragon",
            "abc123",
            "qwerty",
            "qwerty123",
            "123456",
            "1234567",
            "12345678",
            "123456789",
            "111111",
            "000000",
            "5201314",
            "1314520",
        }
    )

    _KEYBOARD_SEQUENCES = (
        "qwerty",
        "wertyu",
        "ertyui",
        "rtyuio",
        "tyuiop",
        "asdfgh",
        "sdfghj",
        "dfghjk",
        "fghjkl",
        "zxcvbn",
        "xcvbnm",
        "qazwsx",
        "wsxedc",
        "edcrfv",
    )

    _CONFUSABLES = {
        "0": "o",
        "1": "l",
        "|": "l",
        "ı": "i",
        "ɩ": "i",
        "ɑ": "a",
        "ɡ": "g",
        "ʏ": "y",
        "ԁ": "d",
        "ӏ": "l",
        "а": "a",
        "в": "b",
        "е": "e",
        "ё": "e",
        "к": "k",
        "м": "m",
        "н": "h",
        "о": "o",
        "р": "p",
        "с": "c",
        "т": "t",
        "у": "y",
        "х": "x",
        "ѕ": "s",
        "і": "i",
        "ј": "j",
        "һ": "h",
        "ԛ": "q",
        "ԝ": "w",
        "α": "a",
        "β": "b",
        "γ": "y",
        "ε": "e",
        "η": "n",
        "ι": "i",
        "κ": "k",
        "ν": "v",
        "ο": "o",
        "ρ": "p",
        "σ": "o",
        "τ": "t",
        "υ": "u",
        "χ": "x",
        "ω": "w",
    }

    def __init__(
        self,
        min_len=8,
        max_len=64,
        max_bytes=128,
        common=(),
        breached_prefixes=(),
        policy_version="v1",
    ):
        self.min_len = int(min_len)
        self.max_len = int(max_len)
        self.max_bytes = int(max_bytes)
        self.policy_version = str(policy_version)

        common_values = self._iter_values(common)
        self._common = frozenset(
            value
            for value in (self.normalize(item) for item in common_values)
            if value
        )

        breach_values = self._iter_values(breached_prefixes)
        self._breached_prefixes = frozenset(
            value
            for value in (self.normalize(item) for item in breach_values)
            if value
        )
        self._breached_hashes = frozenset(
            item.strip().lower()
            for item in breach_values
            if self._looks_like_hex(item.strip())
        )

    @staticmethod
    def _iter_values(values):
        if values is None:
            return ()
        if isinstance(values, dict):
            return tuple(str(value) for value in values)
        if isinstance(values, str):
            return (values,)
        return tuple(str(value) for value in values)

    @staticmethod
    def _looks_like_hex(value):
        return bool(value) and all(
            character in "0123456789abcdefABCDEF" for character in value
        )

    def normalize(self, password):
        if not isinstance(password, str):
            raise PasswordError("invalid", ["invalid_type"], self.policy_version)
        value = unicodedata.normalize("NFKC", password)
        value = value.casefold()
        return unicodedata.normalize("NFKC", value)

    def skeleton(self, value):
        if not isinstance(value, str):
            return ""
        normalized = self.normalize(value)
        decomposed = unicodedata.normalize("NFKD", normalized)
        output = []
        for character in decomposed:
            category = unicodedata.category(character)
            if category.startswith("M") or category in {
                "Cc",
                "Cf",
                "Cs",
                "Cn",
                "Zl",
                "Zp",
            }:
                continue
            if character.isspace():
                continue
            mapped = self._CONFUSABLES.get(character, character)
            if mapped.isalnum() or mapped in {"#", "@"}:
                output.append(mapped)
        return "".join(output)

    def check(self, password, username=None):
        normalized = self.normalize(password)
        safety_rules = self._safety_violations(normalized)
        if safety_rules:
            raise PasswordError("invalid", safety_rules, self.policy_version)

        clusters = self._grapheme_clusters(normalized)
        grapheme_count = len(clusters)
        codepoint_count = len(normalized)
        byte_count = len(normalized.encode("utf-8"))

        if grapheme_count > self.max_len or byte_count > self.max_bytes:
            rules = []
            if grapheme_count > self.max_len:
                rules.append("max_length")
            if byte_count > self.max_bytes:
                rules.append("max_bytes")
            raise PasswordError("too_long", rules, self.policy_version)

        if grapheme_count < self.min_len:
            raise PasswordError("too_short", ["min_length"], self.policy_version)

        weak_rules = self._weak_rules(normalized, clusters, username)
        if weak_rules:
            raise PasswordError("weak", weak_rules, self.policy_version)

        warnings = []
        if normalized and (normalized[0].isspace() or normalized[-1].isspace()):
            warnings.append("leading_trailing_space")

        return {
            "ok": True,
            "version": self.policy_version,
            "policy_version": self.policy_version,
            "normalized": normalized,
            "graphemes": grapheme_count,
            "codepoints": codepoint_count,
            "bytes": byte_count,
            "rules": list(self._RESULT_RULES),
            "warnings": warnings,
        }

    def _safety_violations(self, value):
        rules = []
        for index, character in enumerate(value):
            category = unicodedata.category(character)
            bidi_class = unicodedata.bidirectional(character)

            if character == "\x00":
                rules.append("nul_byte")
                continue
            if character == self._ZWJ and self._valid_emoji_zwj(value, index):
                continue
            if category in self._REJECTED_CATEGORIES:
                if bidi_class in self._BIDI_CONTROLS:
                    rules.append("bidi_control")
                elif category == "Cn":
                    rules.append("unassigned_codepoint")
                elif category == "Cf":
                    rules.append("invisible_format")
                else:
                    rules.append("control_character")
                continue
            if bidi_class in self._BIDI_CONTROLS:
                rules.append("bidi_control")
        return list(dict.fromkeys(rules))

    def _valid_emoji_zwj(self, value, index):
        left = index - 1
        while left >= 0 and self._is_extend(value[left]):
            left -= 1
        right = index + 1
        return (
            left >= 0
            and right < len(value)
            and self._is_extended_pictographic(value[left])
            and self._is_extended_pictographic(value[right])
        )

    def _weak_rules(self, normalized, clusters, username):
        rules = []
        if self._is_common(normalized):
            rules.append("common_password")
        if self._is_pinyin_weak(normalized):
            rules.append("pinyin_weak")
        if self._has_sequence(normalized):
            rules.append("sequence")
        if self._has_repeated_clusters(clusters):
            rules.append("repeated_characters")
        if username is not None and self._contains_username(normalized, str(username)):
            rules.append("username_contained")
        if self._is_breached(normalized):
            rules.append("breached")
        return rules

    def _is_common(self, normalized):
        if normalized in self._common or normalized in self._BUILTIN_COMMON:
            return True

        base = normalized
        while base and not base[-1].isalpha():
            base = base[:-1]
        return len(base) >= 4 and (
            base in self._common or base in self._BUILTIN_COMMON
        )

    def _is_pinyin_weak(self, normalized):
        for root in self._PINYIN_ROOTS:
            if normalized == root:
                return True
            if root not in normalized:
                continue
            remainder = normalized.replace(root, "", 1)
            if remainder and not any(character.isalpha() for character in remainder):
                return True
        return False

    def _has_sequence(self, normalized):
        for sequence in self._KEYBOARD_SEQUENCES:
            if sequence in normalized or sequence[::-1] in normalized:
                return True

        run_length = 1
        previous_delta = 0
        previous = ""
        for character in normalized:
            if (
                previous
                and character.isascii()
                and previous.isascii()
                and character.isdigit()
                and previous.isdigit()
            ):
                delta = ord(character) - ord(previous)
            else:
                delta = 0

            if abs(delta) == 1:
                if delta == previous_delta:
                    run_length += 1
                else:
                    run_length = 2
                    previous_delta = delta
            else:
                run_length = 1
                previous_delta = 0

            if run_length >= 6:
                return True
            previous = character
        return False

    @staticmethod
    def _has_repeated_clusters(clusters):
        run_length = 1
        for previous, current in zip(clusters, clusters[1:]):
            if previous == current:
                run_length += 1
                if run_length >= 4:
                    return True
            else:
                run_length = 1

        total = len(clusters)
        for period in range(1, min(4, total // 3) + 1):
            if total >= period * 3 and total % period == 0:
                pattern = clusters[:period]
                if clusters == pattern * (total // period):
                    return True
        return False

    def _contains_username(self, normalized, username):
        username_normalized = self.normalize(username)
        candidates = {username_normalized}
        if "@" in username_normalized:
            candidates.add(username_normalized.split("@", 1)[0])
        candidates.discard("")

        normalized_skeleton = self.skeleton(normalized)
        for candidate in candidates:
            if candidate in normalized:
                return True
            candidate_skeleton = self.skeleton(candidate)
            if candidate_skeleton and candidate_skeleton in normalized_skeleton:
                return True
        return False

    def _is_breached(self, normalized):
        for prefix in self._breached_prefixes:
            if normalized.startswith(prefix):
                return True

        if not self._breached_hashes:
            return False

        prefixes = []
        for character in normalized:
            prefixes.append(character)
            candidate = "".join(prefixes).encode("utf-8")
            for algorithm in ("sha1", "sha256"):
                digest = hashlib.new(algorithm, candidate).hexdigest()
                if any(digest.startswith(value) for value in self._breached_hashes):
                    return True
        return False

    @classmethod
    def _grapheme_clusters(cls, value):
        clusters = []
        for index, character in enumerate(value):
            if not clusters:
                clusters.append(character)
                continue

            previous = value[index - 1]
            if previous == "\r" and character == "\n":
                clusters[-1] += character
            elif cls._is_control(previous) and previous != cls._ZWJ:
                clusters.append(character)
            elif cls._is_control(character) and character != cls._ZWJ:
                clusters.append(character)
            elif cls._is_hangul_l(previous) and cls._is_hangul_l_or_v_or_lv_lvt(
                character
            ):
                clusters[-1] += character
            elif cls._is_hangul_lv_or_v(previous) and cls._is_hangul_v_or_t(character):
                clusters[-1] += character
            elif cls._is_hangul_lvt_or_t(previous) and cls._is_hangul_t(character):
                clusters[-1] += character
            elif cls._is_extend(character) or character == cls._ZWJ:
                clusters[-1] += character
            elif cls._is_spacing_mark(character):
                clusters[-1] += character
            elif cls._is_prepend(previous):
                clusters[-1] += character
            elif cls._is_extended_pictographic(
                character
            ) and cls._ends_with_emoji_zwj(value, index):
                clusters[-1] += character
            elif cls._is_regional_indicator(
                character
            ) and cls._regional_indicator_pair(value, index):
                clusters[-1] += character
            else:
                clusters.append(character)
        return clusters

    @classmethod
    def _ends_with_emoji_zwj(cls, value, index):
        if index == 0 or value[index - 1] != cls._ZWJ:
            return False
        left = index - 2
        while left >= 0 and cls._is_extend(value[left]):
            left -= 1
        return left >= 0 and cls._is_extended_pictographic(value[left])

    @classmethod
    def _regional_indicator_pair(cls, value, index):
        count = 0
        position = index - 1
        while position >= 0 and cls._is_regional_indicator(value[position]):
            count += 1
            position -= 1
        return count % 2 == 1

    @staticmethod
    def _is_control(character):
        return unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}

    @staticmethod
    def _is_extend(character):
        codepoint = ord(character)
        return (
            unicodedata.category(character) in {"Mn", "Me"}
            or 0x1F3FB <= codepoint <= 0x1F3FF
            or 0xE0100 <= codepoint <= 0xE01EF
        )

    @staticmethod
    def _is_spacing_mark(character):
        return unicodedata.category(character) == "Mc"

    @staticmethod
    def _is_prepend(character):
        codepoint = ord(character)
        return (
            0x0600 <= codepoint <= 0x0605
            or codepoint in {0x06DD, 0x070F, 0x08E2, 0x0D4E, 0x110BD, 0x110CD}
            or 0x111C2 <= codepoint <= 0x111C3
            or codepoint in {0x1193F, 0x11941, 0x11A3A, 0x11D46, 0x11F02}
            or 0x11A84 <= codepoint <= 0x11A89
        )

    @staticmethod
    def _is_regional_indicator(character):
        return 0x1F1E6 <= ord(character) <= 0x1F1FF

    @staticmethod
    def _is_hangul_l(character):
        codepoint = ord(character)
        return 0x1100 <= codepoint <= 0x115F or 0xA960 <= codepoint <= 0xA97C

    @staticmethod
    def _is_hangul_v(character):
        codepoint = ord(character)
        return 0x1160 <= codepoint <= 0x11A7 or 0xD7B0 <= codepoint <= 0xD7C6

    @staticmethod
    def _is_hangul_t(character):
        codepoint = ord(character)
        return 0x11A8 <= codepoint <= 0x11FF or 0xD7CB <= codepoint <= 0xD7FB

    @classmethod
    def _is_hangul_lv_or_v(cls, character):
        codepoint = ord(character)
        return cls._is_hangul_v(character) or (
            0xAC00 <= codepoint <= 0xD7A3 and (codepoint - 0xAC00) % 28 == 0
        )

    @classmethod
    def _is_hangul_lvt_or_t(cls, character):
        codepoint = ord(character)
        return cls._is_hangul_t(character) or (
            0xAC00 <= codepoint <= 0xD7A3 and (codepoint - 0xAC00) % 28 != 0
        )

    @classmethod
    def _is_hangul_l_or_v_or_lv_lvt(cls, character):
        codepoint = ord(character)
        return (
            cls._is_hangul_l(character)
            or cls._is_hangul_v(character)
            or 0xAC00 <= codepoint <= 0xD7A3
        )

    @classmethod
    def _is_hangul_v_or_t(cls, character):
        return cls._is_hangul_v(character) or cls._is_hangul_t(character)

    @staticmethod
    def _is_extended_pictographic(character):
        codepoint = ord(character)
        return (
            0x1F000 <= codepoint <= 0x1FAFF
            or 0x1FC00 <= codepoint <= 0x1FFFD
            or codepoint
            in {
                0x00A9,
                0x00AE,
                0x203C,
                0x2049,
                0x2122,
                0x2139,
                0x2328,
                0x23CF,
                0x24C2,
                0x25AA,
                0x25AB,
                0x25B6,
                0x25C0,
                0x260E,
                0x2611,
                0x2618,
                0x261D,
                0x2620,
                0x2626,
                0x262A,
                0x2640,
                0x2642,
                0x2663,
                0x2665,
                0x2666,
                0x2668,
                0x267B,
                0x267E,
                0x267F,
                0x2699,
                0x26A7,
                0x26C8,
                0x26CE,
                0x26CF,
                0x26D1,
                0x26D3,
                0x26E9,
                0x26F0,
                0x26F5,
                0x26F7,
                0x26F8,
                0x26F9,
                0x26FA,
                0x26FD,
                0x2702,
                0x2705,
                0x2708,
                0x2709,
                0x270A,
                0x270B,
                0x270C,
                0x270D,
                0x270F,
                0x2712,
                0x2714,
                0x2716,
                0x271D,
                0x2721,
                0x2728,
                0x2733,
                0x2734,
                0x2744,
                0x2747,
                0x274C,
                0x274E,
                0x2753,
                0x2754,
                0x2755,
                0x2757,
                0x2763,
                0x2764,
                0x2795,
                0x2796,
                0x2797,
                0x27A1,
                0x27B0,
                0x27BF,
                0x2934,
                0x2935,
                0x2B05,
                0x2B06,
                0x2B07,
                0x2B1B,
                0x2B1C,
                0x2B50,
                0x2B55,
                0x3030,
                0x303D,
                0x3297,
                0x3299,
            }
            or 0x2194 <= codepoint <= 0x2199
            or 0x21A9 <= codepoint <= 0x21AA
            or 0x231A <= codepoint <= 0x231B
            or 0x23E9 <= codepoint <= 0x23F3
            or 0x23F8 <= codepoint <= 0x23FA
            or 0x25FB <= codepoint <= 0x25FE
            or 0x2600 <= codepoint <= 0x2604
            or 0x2614 <= codepoint <= 0x2615
            or 0x2622 <= codepoint <= 0x2623
            or 0x262E <= codepoint <= 0x262F
            or 0x2638 <= codepoint <= 0x263A
            or 0x2648 <= codepoint <= 0x2653
            or 0x265F <= codepoint <= 0x2660
            or 0x2692 <= codepoint <= 0x2697
            or 0x269B <= codepoint <= 0x269C
            or 0x26A0 <= codepoint <= 0x26A1
            or 0x26AA <= codepoint <= 0x26AB
            or 0x26B0 <= codepoint <= 0x26B1
            or 0x26BD <= codepoint <= 0x26BE
            or 0x26C4 <= codepoint <= 0x26C5
            or 0x26D4 <= codepoint <= 0x26D4
            or 0x26EA <= codepoint <= 0x26EA
            or 0x26F2 <= codepoint <= 0x26F3
            or 0x26F9 <= codepoint <= 0x26F9
            or 0x270A <= codepoint <= 0x270B
        )
