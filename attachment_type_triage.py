import re


class AttachmentTypeTriage:
    EXTENSION_TYPES = {
        "png": "png",
        "apng": "png",
        "jpg": "jpeg",
        "jpeg": "jpeg",
        "jpe": "jpeg",
        "jfif": "jpeg",
        "gif": "gif",
        "webp": "webp",
        "bmp": "bmp",
        "dib": "bmp",
        "tif": "tiff",
        "tiff": "tiff",
        "ico": "ico",
        "cur": "cur",
        "heic": "heic",
        "heif": "heic",
        "avif": "avif",
        "svg": "svg",
        "svgz": "gzip",
        "pdf": "pdf",
        "txt": "text",
        "text": "text",
        "log": "text",
        "md": "text",
        "markdown": "text",
        "csv": "text",
        "tsv": "text",
        "json": "text",
        "xml": "text",
        "yaml": "text",
        "yml": "text",
        "ini": "text",
        "cfg": "text",
        "conf": "text",
        "rst": "text",
        "tex": "text",
        "rtf": "rtf",
        "docx": "ooxml",
        "docm": "ooxml",
        "dotx": "ooxml",
        "dotm": "ooxml",
        "xlsx": "ooxml",
        "xlsm": "ooxml",
        "xlsb": "ooxml",
        "xltx": "ooxml",
        "xltm": "ooxml",
        "pptx": "ooxml",
        "pptm": "ooxml",
        "potx": "ooxml",
        "potm": "ooxml",
        "ppsx": "ooxml",
        "ppsm": "ooxml",
        "odt": "odf",
        "ods": "odf",
        "odp": "odf",
        "odg": "odf",
        "doc": "ole",
        "xls": "ole",
        "ppt": "ole",
        "msi": "ole",
        "zip": "zip",
        "jar": "zip",
        "apk": "zip",
        "gzip": "gzip",
        "gz": "gzip",
        "tgz": "gzip",
        "bz2": "bzip2",
        "bzip2": "bzip2",
        "tbz2": "bzip2",
        "xz": "xz",
        "txz": "xz",
        "7z": "7z",
        "rar": "rar",
        "tar": "tar",
        "zst": "zstd",
        "zstd": "zstd",
    }

    SCRIPT_EXTENSIONS = {
        "php",
        "php3",
        "php4",
        "php5",
        "phtml",
        "phar",
        "js",
        "mjs",
        "cjs",
        "jsp",
        "asp",
        "aspx",
        "cgi",
        "pl",
        "py",
        "rb",
        "sh",
        "bash",
        "bat",
        "cmd",
        "ps1",
        "exe",
        "dll",
        "com",
        "scr",
        "vbs",
        "wsf",
        "hta",
    }

    MIME_TYPES = {
        "image/png": "png",
        "image/apng": "png",
        "image/jpeg": "jpeg",
        "image/jpg": "jpeg",
        "image/pjpeg": "jpeg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/x-ms-bmp": "bmp",
        "image/tiff": "tiff",
        "image/x-icon": "ico",
        "image/vnd.microsoft.icon": "ico",
        "image/x-cursor": "cur",
        "image/heic": "heic",
        "image/heif": "heic",
        "image/avif": "avif",
        "image/svg+xml": "svg",
        "application/pdf": "pdf",
        "application/rtf": "rtf",
        "text/rtf": "rtf",
        "application/zip": "zip",
        "application/x-zip-compressed": "zip",
        "application/x-zip": "zip",
        "application/gzip": "gzip",
        "application/x-gzip": "gzip",
        "application/x-bzip2": "bzip2",
        "application/x-bzip": "bzip2",
        "application/x-xz": "xz",
        "application/x-7z-compressed": "7z",
        "application/vnd.rar": "rar",
        "application/x-rar": "rar",
        "application/x-rar-compressed": "rar",
        "application/x-tar": "tar",
        "application/zstd": "zstd",
        "application/x-zstd": "zstd",
        "application/msword": "ole",
        "application/vnd.ms-excel": "ole",
        "application/vnd.ms-powerpoint": "ole",
        "application/vnd.oasis.opendocument.text": "odf",
        "application/vnd.oasis.opendocument.spreadsheet": "odf",
        "application/vnd.oasis.opendocument.presentation": "odf",
        "application/vnd.oasis.opendocument.graphics": "odf",
    }

    MACRO_EXTENSIONS = {
        "docm",
        "dotm",
        "xlsm",
        "xlsb",
        "xltm",
        "pptm",
        "potm",
        "ppsm",
    }

    OFFICE_FAMILIES = {
        "docx": "word",
        "docm": "word",
        "dotx": "word",
        "dotm": "word",
        "xlsx": "excel",
        "xlsm": "excel",
        "xlsb": "excel",
        "xltx": "excel",
        "xltm": "excel",
        "pptx": "presentation",
        "pptm": "presentation",
        "potx": "presentation",
        "potm": "presentation",
        "ppsx": "presentation",
        "ppsm": "presentation",
    }

    COMPOUND_EXTENSIONS = {
        ("tar", "gz"),
        ("tar", "bz2"),
        ("tar", "xz"),
        ("tar", "zst"),
    }

    ARCHIVE_TYPES = {
        "zip",
        "ooxml",
        "odf",
        "gzip",
        "bzip2",
        "xz",
        "7z",
        "rar",
        "tar",
        "zstd",
    }

    IMAGE_TYPES = {
        "png",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "tiff",
        "ico",
        "cur",
        "heic",
        "avif",
        "svg",
    }

    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    JPEG_MAGIC = b"\xff\xd8\xff"
    GIF_MAGICS = (b"GIF87a", b"GIF89a")
    PDF_MAGIC = b"%PDF-"
    ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

    def __init__(self, policy="reject"):
        self.policy = str(policy or "reject").strip().lower()

    def inspect(self, data, filename, declared_type=None):
        raw = self._as_bytes(data)
        name = self._basename(filename)
        extension = self._extension(name)
        declared_raw, declared_expected = self._declared_type(declared_type)
        detected = self._detect(raw, extension)
        detected_type = detected["type"]
        conflicts = []
        reasons = []

        def add_conflict(conflict, reason):
            if conflict not in conflicts:
                conflicts.append(conflict)
            if reason and reason not in reasons:
                reasons.append(reason)

        if detected_type == "empty":
            add_conflict("empty_file", "file is empty")
        elif detected.get("content_hint") == "script":
            reason = "content contains executable script markers"
            if reason not in reasons:
                reasons.append(reason)

        for conflict in detected.get("conflicts", {}):
            add_conflict(conflict, detected["conflicts"].get(conflict))

        expected_extension_type = self._extension_type(extension)
        if expected_extension_type and not self._compatible(detected_type, expected_extension_type):
            add_conflict(
                "extension_mismatch",
                "extension .%s expects %s but bytes indicate %s"
                % (extension, expected_extension_type, detected_type),
            )

        double_extension = self._has_double_extension(name, extension)
        if double_extension:
            add_conflict(
                "double_extension",
                "filename has a second extension before .%s" % extension,
            )

        if declared_expected and not self._compatible(detected_type, declared_expected):
            add_conflict(
                "declared_mismatch",
                "declared type %s expects %s but bytes indicate %s"
                % (declared_raw, declared_expected, detected_type),
            )

        if detected_type == "ooxml" and extension in self.OFFICE_FAMILIES:
            expected_family = self.OFFICE_FAMILIES[extension]
            actual_family = detected.get("office_family")
            if actual_family and actual_family != expected_family:
                add_conflict(
                    "office_extension_mismatch",
                    "extension .%s expects %s content but bytes indicate %s"
                    % (extension, expected_family, actual_family),
                )
                add_conflict(
                    "extension_mismatch",
                    "content family does not match extension .%s" % extension,
                )

            macro_expected = extension in self.MACRO_EXTENSIONS
            if macro_expected != bool(detected.get("macro")):
                add_conflict(
                    "macro_extension_mismatch",
                    "macro content state does not match extension .%s" % extension,
                )
                add_conflict(
                    "extension_mismatch",
                    "macro content state does not match extension .%s" % extension,
                )

        incomplete = bool(detected.get("incomplete"))
        if incomplete:
            reasons.append(
                detected.get("incomplete_reason")
                or "file is truncated or structurally incomplete"
            )

        if detected.get("macro"):
            reason = "document contains macro-enabled content"
            if reason not in reasons:
                reasons.append(reason)

        if detected_type == "unknown" and not reasons:
            reasons.append("content type could not be identified from its bytes")

        needs_review = bool(
            conflicts
            or incomplete
            or detected_type in {"empty", "unknown"}
            or detected.get("macro")
        )
        accepted_by_content = detected_type not in {"empty", "unknown"} and not incomplete
        if self.policy in {"reject", "strict", "quarantine"}:
            accepted = accepted_by_content and not conflicts
        else:
            accepted = accepted_by_content

        if not accepted:
            decision = "reject"
        elif needs_review:
            decision = "review"
        else:
            decision = "accept"

        return {
            "type": detected_type,
            "confidence": round(float(detected.get("confidence", 0.0)), 2),
            "conflicts": conflicts,
            "needs_review": needs_review,
            "incomplete": incomplete,
            "macro": bool(detected.get("macro")),
            "extension": extension,
            "expected_extension_type": expected_extension_type,
            "declared_type": declared_raw,
            "expected_declared_type": declared_expected,
            "double_extension": double_extension,
            "active_content": "active_content" in conflicts,
            "external_reference": "external_reference" in conflicts,
            "macro_extension_mismatch": "macro_extension_mismatch" in conflicts,
            "script_content": detected.get("content_hint") == "script",
            "trailing_archive": "trailing_archive" in conflicts,
            "polyglot": "polyglot" in conflicts,
            "accepted": accepted,
            "decision": decision,
            "reasons": reasons,
        }

    def _detect(self, raw, extension):
        size = len(raw)
        if size == 0:
            return self._result("empty", 1.0)

        if raw.startswith(self.PNG_MAGIC):
            incomplete = size < 33 or raw[12:16] != b"IHDR"
            return self._result(
                "png",
                0.98 if not incomplete else 0.75,
                incomplete=incomplete,
                incomplete_reason="PNG is missing a complete IHDR header",
                conflicts=self._trailing_archive_conflicts(raw, "png"),
            )

        if raw.startswith(self.JPEG_MAGIC):
            incomplete = size < 4 or raw.rfind(b"\xff\xd9") < 4
            return self._result(
                "jpeg",
                0.98 if not incomplete else 0.75,
                incomplete=incomplete,
                incomplete_reason="JPEG is missing an EOI marker",
                conflicts=self._trailing_archive_conflicts(raw, "jpeg"),
            )

        if raw.startswith(self.GIF_MAGICS):
            incomplete = size < 13
            return self._result(
                "gif",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="GIF is missing its logical screen descriptor",
                conflicts=self._trailing_archive_conflicts(raw, "gif"),
            )

        if raw.startswith(b"RIFF"):
            if size >= 12 and raw[8:12] == b"WEBP":
                return self._result(
                    "webp",
                    0.98,
                    conflicts=self._trailing_archive_conflicts(raw, "webp"),
                )
            if size < 12:
                return self._result(
                    "webp",
                    0.45,
                    incomplete=True,
                    incomplete_reason="RIFF/WEBP header is truncated",
                )
            return self._result("unknown", 0.1)

        if raw.startswith(b"BM"):
            incomplete = size < 14
            return self._result(
                "bmp",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="BMP header is truncated",
                conflicts=self._trailing_archive_conflicts(raw, "bmp"),
            )

        if raw.startswith((b"II*\x00", b"MM\x00*")):
            incomplete = size < 8
            return self._result(
                "tiff",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="TIFF header is truncated",
                conflicts=self._trailing_archive_conflicts(raw, "tiff"),
            )

        if raw.startswith(b"\x00\x00\x01\x00"):
            incomplete = size < 6
            return self._result(
                "ico",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="ICO directory header is truncated",
                conflicts=self._trailing_archive_conflicts(raw, "ico"),
            )

        if raw.startswith(b"\x00\x00\x02\x00"):
            incomplete = size < 6
            return self._result(
                "cur",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="CUR directory header is truncated",
                conflicts=self._trailing_archive_conflicts(raw, "cur"),
            )

        if raw.startswith(self.PDF_MAGIC):
            incomplete = b"%%EOF" not in raw
            return self._result(
                "pdf",
                0.98 if not incomplete else 0.75,
                incomplete=incomplete,
                incomplete_reason="PDF is missing an EOF marker",
                conflicts=self._trailing_archive_conflicts(raw, "pdf"),
            )

        if raw.startswith(self.ZIP_MAGICS):
            office = self._office_structure(raw)
            if office["type"] == "ooxml":
                return self._result(
                    "ooxml",
                    0.97,
                    macro=office["macro"],
                    office_family=office["family"],
                )
            if office["type"] == "odf":
                return self._result("odf", 0.95)
            return self._result("zip", 0.9)

        if raw.startswith(b"\x1f\x8b"):
            incomplete = size < 10 or raw[2] != 8
            return self._result(
                "gzip",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="GZIP header is truncated",
            )

        if raw.startswith(b"BZh"):
            incomplete = size < 4
            return self._result(
                "bzip2",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="BZIP2 header is truncated",
            )

        if raw.startswith(b"\xfd7zXZ\x00"):
            incomplete = size < 12
            return self._result(
                "xz",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="XZ header is truncated",
            )

        if raw.startswith(b"7z\xbc\xaf\x27\x1c"):
            incomplete = size < 32
            return self._result(
                "7z",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="7Z header is truncated",
            )

        if raw.startswith(b"Rar!\x1a\x07"):
            return self._result("rar", 0.97)

        if raw.startswith(b"\x28\xb5\x2f\xfd"):
            incomplete = size < 4
            return self._result(
                "zstd",
                0.97 if not incomplete else 0.7,
                incomplete=incomplete,
                incomplete_reason="Zstandard frame header is truncated",
            )

        if size >= 262 and raw[257:262] == b"ustar":
            return self._result("tar", 0.95)

        if raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            lower = raw.lower()
            macro = b"vbaproject" in lower or b"_vba_project" in lower
            return self._result("ole", 0.97, macro=macro)

        if size >= 12 and raw[4:8] == b"ftyp":
            brand = raw[8:12].lower()
            if brand in {
                b"heic",
                b"heix",
                b"hevc",
                b"hevx",
                b"heim",
                b"heis",
                b"mif1",
                b"msf1",
            }:
                return self._result(
                    "heic",
                    0.95,
                    conflicts=self._trailing_archive_conflicts(raw, "heic"),
                )
            if brand in {b"avif", b"avis"}:
                return self._result(
                    "avif",
                    0.95,
                    conflicts=self._trailing_archive_conflicts(raw, "avif"),
                )

        textual = self._decoded_text(raw)
        if textual is not None:
            text, encoding = textual
            if self._looks_like_svg(text):
                conflicts = self._svg_conflicts(text)
                incomplete = not self._svg_is_closed(text)
                return self._result(
                    "svg",
                    0.95 if not incomplete else 0.75,
                    incomplete=incomplete,
                    incomplete_reason="SVG root element is not closed",
                    conflicts=conflicts,
                )
            if self._looks_like_script(text):
                return self._result("unknown", 0.15, content_hint="script")
            if self._looks_like_rtf(text):
                return self._result("rtf", 0.9)
            return self._result("text", 0.85 if encoding else 0.8)

        partial = self._partial_magic(raw)
        if partial:
            return self._result(
                partial,
                0.35,
                incomplete=True,
                incomplete_reason="known file signature is truncated",
            )

        return self._result("unknown", 0.05)

    @staticmethod
    def _office_structure(raw):
        lower = raw.lower()
        has_content_types = b"[content_types].xml" in lower
        has_rels = b"_rels/.rels" in lower
        has_office_family = b"word/" in lower or b"xl/" in lower or b"ppt/" in lower
        macro = b"vbaproject" in lower or b"vbadata.xml" in lower

        if b"mimetypeapplication/vnd.oasis.opendocument" in lower:
            return {"type": "odf", "macro": False, "family": None}

        if has_content_types or has_rels or has_office_family or macro:
            family = None
            if b"word/" in lower:
                family = "word"
            elif b"xl/" in lower:
                family = "excel"
            elif b"ppt/" in lower:
                family = "presentation"
            return {"type": "ooxml", "macro": macro, "family": family}

        return {"type": "zip", "macro": False, "family": None}

    def _svg_conflicts(self, text):
        lower = text.lower()
        conflicts = {}

        active = bool(
            re.search(r"<\s*script\b", lower)
            or re.search(r"<\s*foreignobject\b", lower)
            or re.search(r"javascript\s*:", lower)
            or re.search(r"<\s*(?:iframe|embed|object)\b", lower)
            or re.search(r"\son[a-z]+\s*=", lower)
        )
        if active:
            conflicts["active_content"] = "SVG contains script or active content"

        external = False
        external_value = None
        for match in re.finditer(
            r"\b(?:xlink:href|href|src)\s*=\s*([\"'])(.*?)\1",
            text,
            re.IGNORECASE | re.DOTALL,
        ):
            value = match.group(2).strip()
            if self._is_external_url(value):
                external = True
                external_value = value
                break
        if not external:
            for match in re.finditer(
                r"url\(\s*([\"']?)([^)'\"\s]+)\1\s*\)",
                text,
                re.IGNORECASE,
            ):
                value = match.group(2).strip()
                if self._is_external_url(value):
                    external = True
                    external_value = value
                    break
        if not external and re.search(r"@import\b", lower):
            external = True
            external_value = "@import"

        if external:
            conflicts["external_reference"] = (
                "SVG references external resource %s" % external_value
            )

        return conflicts

    @staticmethod
    def _is_external_url(value):
        lower = value.lower()
        if lower.startswith(("http://www.w3.org/", "https://www.w3.org/")):
            return False
        if lower.startswith(("#", "data:", "javascript:", "mailto:", "tel:")):
            return False
        return bool(value)

    @staticmethod
    def _looks_like_svg(text):
        head = text.lstrip("\ufeff \t\r\n")[:8192]
        return bool(re.search(r"<\s*svg(?:\s|>)", head, re.IGNORECASE))

    @staticmethod
    def _svg_is_closed(text):
        return bool(
            re.search(r"</\s*svg\s*>", text, re.IGNORECASE)
            or re.search(r"<\s*svg\b[^>]*/\s*>", text, re.IGNORECASE | re.DOTALL)
        )

    @staticmethod
    def _looks_like_script(text):
        head = text.lstrip("\ufeff \t\r\n")[:4096]
        return bool(
            re.search(r"<\?(?!xml)\b", head, re.IGNORECASE)
            or re.search(r"<\s*script\b", head, re.IGNORECASE)
            or re.search(r"^#!\s*/", head)
            or re.search(
                r"(?:^|\s)(?:eval|system|exec|shell_exec|alert|prompt|confirm)\s*\(",
                head,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _looks_like_rtf(text):
        return text.lstrip("\ufeff \t\r\n")[:5].lower() == "{\\rtf"

    def _decoded_text(self, raw):
        encoding = None
        if raw.startswith((b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00")):
            encoding = "utf-32"
        elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        elif raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"

        candidates = []
        if encoding:
            candidates.append(encoding)
        else:
            candidates.append("utf-8")
            if b"\x00" in raw and len(raw) % 2 == 0:
                candidates.extend(("utf-16-le", "utf-16-be"))

        for candidate in candidates:
            try:
                text = raw.decode(candidate)
            except (UnicodeDecodeError, LookupError):
                continue
            text = text.lstrip("\ufeff")
            if self._printable_ratio(text) >= 0.95:
                return text, encoding or candidate
        return None

    @staticmethod
    def _printable_ratio(text):
        if not text:
            return 1.0
        printable = 0
        for char in text:
            if char in "\r\n\t\f\b" or char.isprintable():
                printable += 1
        return printable / len(text)

    def _trailing_archive_conflicts(self, raw, primary_type):
        if primary_type in self.ARCHIVE_TYPES:
            return {}

        start = 1
        if primary_type == "pdf":
            eof = raw.rfind(b"%%EOF")
            start = eof + 5 if eof >= 0 else 5
        elif primary_type == "jpeg":
            eoi = raw.rfind(b"\xff\xd9")
            start = eoi + 2 if eoi >= 4 else 4
        elif primary_type == "png":
            iend = raw.rfind(b"IEND")
            start = iend + 8 if iend >= 0 else 8
        elif primary_type == "gif":
            trailer = raw.rfind(b"\x3b")
            start = trailer + 1 if trailer >= 0 else 13

        signatures = {
            b"PK\x03\x04": "zip",
            b"PK\x05\x06": "zip",
            b"\x1f\x8b\x08": "gzip",
            b"BZh": "bzip2",
            b"\xfd7zXZ\x00": "xz",
            b"7z\xbc\xaf\x27\x1c": "7z",
            b"Rar!\x1a\x07": "rar",
            b"\x28\xb5\x2f\xfd": "zstd",
        }

        found = []
        for signature, archive_type in signatures.items():
            position = raw.find(signature, start)
            if position >= 0 and archive_type not in found:
                found.append(archive_type)

        if not found:
            return {}

        conflicts = {
            "trailing_archive": (
                "archive data is appended after the primary %s content" % primary_type
            )
        }
        if primary_type not in self.IMAGE_TYPES:
            conflicts["polyglot"] = (
                "file is valid as %s and also contains an appended archive" % primary_type
            )
        return conflicts

    def _extension_type(self, extension):
        if not extension:
            return None
        if extension in self.SCRIPT_EXTENSIONS:
            return "script"
        return self.EXTENSION_TYPES.get(extension)

    def _declared_type(self, declared_type):
        if declared_type is None:
            return None, None
        if isinstance(declared_type, bytes):
            declared_type = declared_type.decode("utf-8", "replace")
        value = str(declared_type).strip().lower()
        if not value:
            return None, None
        mime = value.split(";", 1)[0].strip()
        if mime in {"", "*/*", "application/octet-stream", "binary/octet-stream"}:
            return mime or None, None

        expected = self.MIME_TYPES.get(mime)
        if expected is None and mime.startswith("text/"):
            expected = "text"
        if expected is None and "openxmlformats-officedocument" in mime:
            expected = "ooxml"
        if expected is None and "macroenabled" in mime:
            expected = "ooxml"
        if expected is None and mime in {"application/vnd.ms-office", "application/x-ole-storage"}:
            expected = "ole"
        if expected is None and mime.startswith("."):
            expected = self._extension_type(mime[1:])
        if expected is None and mime in self.EXTENSION_TYPES:
            expected = self.EXTENSION_TYPES[mime]
        return mime, expected

    def _compatible(self, actual, expected):
        if expected is None:
            return True
        if actual == expected:
            return True
        if expected == "script":
            return False
        if actual in {"ooxml", "odf"} and expected == "zip":
            return True
        return False

    def _has_double_extension(self, filename, extension):
        if not extension or "." not in filename:
            return False
        stem = filename[: -(len(extension) + 1)]
        if not stem:
            return False
        if stem.startswith(".") and "." not in stem[1:]:
            return False
        if "." not in stem:
            return False
        previous = stem.rsplit(".", 1)[1].lower()
        return (previous, extension) not in self.COMPOUND_EXTENSIONS

    @staticmethod
    def _basename(filename):
        if filename is None:
            return ""
        if isinstance(filename, bytes):
            filename = filename.decode("utf-8", "replace")
        return str(filename).replace("\\", "/").rsplit("/", 1)[-1]

    @staticmethod
    def _extension(filename):
        if not filename or "." not in filename:
            return ""
        return filename.rsplit(".", 1)[1].strip().lower()

    @staticmethod
    def _as_bytes(data):
        if data is None:
            return b""
        if isinstance(data, bytes):
            return data
        if isinstance(data, (bytearray, memoryview)):
            return bytes(data)
        try:
            return bytes(data)
        except TypeError as exc:
            raise TypeError("data must be bytes-like") from exc

    @staticmethod
    def _partial_magic(raw):
        checks = (
            (AttachmentTypeTriage.PNG_MAGIC, "png"),
            (AttachmentTypeTriage.JPEG_MAGIC, "jpeg"),
            (b"GIF89a", "gif"),
            (b"GIF87a", "gif"),
            (AttachmentTypeTriage.PDF_MAGIC, "pdf"),
            (b"%PDF", "pdf"),
            (b"PK\x03\x04", "zip"),
        )
        for magic, file_type in checks:
            if len(raw) < len(magic) and magic.startswith(raw):
                return file_type
        return None

    @staticmethod
    def _result(
        file_type,
        confidence,
        incomplete=False,
        incomplete_reason=None,
        macro=False,
        office_family=None,
        content_hint=None,
        conflicts=None,
    ):
        return {
            "type": file_type,
            "confidence": confidence,
            "incomplete": incomplete,
            "incomplete_reason": incomplete_reason,
            "macro": macro,
            "office_family": office_family,
            "content_hint": content_hint,
            "conflicts": conflicts or {},
        }
