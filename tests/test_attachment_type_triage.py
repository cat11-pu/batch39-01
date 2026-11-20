import attachment_type_triage as at

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
PDF = b"%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF"
ZIP = b"PK\x03\x04" + b"\x14\x00\x00\x00" + b"\x00" * 20
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 10 + b"\xff\xd9"
GIF = b"GIF89a" + b"\x01\x00\x01\x00" + b"\x00" * 8
WEBP = b"RIFF" + (20).to_bytes(4, "little") + b"WEBP" + b"VP8 "
GZIP = b"\x1f\x8b\x08\x00" + b"\x00" * 10
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def triage(data, filename, declared=None):
    return at.AttachmentTypeTriage().inspect(data, filename, declared)


def test_script_renamed_as_png_is_rejected():
    result = triage(b"<?php echo 1; ?>", "shell.png")
    assert result["type"] == "unknown"
    assert "extension_mismatch" in result["conflicts"]
    assert result["needs_review"] is True


def test_pdf_with_appended_zip_is_a_polyglot():
    result = triage(PDF + ZIP, "contract.pdf")
    assert result["type"] == "pdf"
    assert "polyglot" in result["conflicts"]


def test_truncated_png_is_incomplete():
    result = triage(b"\x89PNG\r\n\x1a\n", "a.png")
    assert result["type"] == "png"
    assert result["incomplete"] is True


def test_utf16_text_with_bom_is_text():
    result = triage(b"\xff\xfe" + "hello".encode("utf-16-le"), "note.txt")
    assert result["type"] == "text"


def test_svg_with_script_has_active_content():
    result = triage(SVG, "logo.svg", "image/svg+xml")
    assert result["type"] == "svg"
    assert "active_content" in result["conflicts"]
    assert result["needs_review"] is True


def test_macro_enabled_office_document_is_flagged():
    data = ZIP + b"vbaProject.bin" + b"[Content_Types].xml"
    result = triage(data, "quote.docm")
    assert result["type"] == "ooxml"
    assert result["macro"] is True


def test_jpeg_with_trailing_archive_is_flagged():
    result = triage(JPEG + ZIP, "photo.jpg")
    assert result["type"] == "jpeg"
    assert "trailing_archive" in result["conflicts"]


def test_declared_type_mismatch_is_flagged():
    result = triage(PNG, "a.png", "application/pdf")
    assert "declared_mismatch" in result["conflicts"]


def test_zero_byte_file_is_rejected():
    result = triage(b"", "empty.bin")
    assert result["type"] == "empty"
    assert result["needs_review"] is True


def test_icon_and_cursor_magic_are_distinguished():
    icon = b"\x00\x00\x01\x00" + b"\x01\x00" + b"\x00" * 20
    cursor = b"\x00\x00\x02\x00" + b"\x01\x00" + b"\x00" * 20
    assert triage(icon, "a.ico")["type"] == "ico"
    assert triage(cursor, "a.cur")["type"] == "cur"


def test_uppercase_extension_is_accepted():
    result = triage(PNG, "A.PNG")
    assert result["type"] == "png"
    assert "extension_mismatch" not in result["conflicts"]


def test_double_extension_is_reported():
    result = triage(PNG, "shell.php.png")
    assert result["type"] == "png"
    assert "double_extension" in result["conflicts"]


def test_gzip_and_zip_are_distinguished():
    assert triage(GZIP, "a.gz")["type"] == "gzip"
    assert triage(ZIP, "a.zip")["type"] == "zip"


def test_webp_is_detected_from_offset_eight():
    result = triage(WEBP, "a.webp")
    assert result["type"] == "webp"


def test_inspection_is_repeatable_and_does_not_mutate_input():
    data = bytearray(PNG)
    before = bytes(data)
    first = at.AttachmentTypeTriage().inspect(data, "a.png")
    second = at.AttachmentTypeTriage().inspect(data, "a.png")
    assert first == second
    assert bytes(data) == before
