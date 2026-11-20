import hashlib

import pem_span_scrubber as ps

RSA = b"-----BEGIN RSA PRIVATE KEY-----\nMIIEAAAA\n-----END RSA PRIVATE KEY-----"
OPENSSH = b"-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA==\n-----END OPENSSH PRIVATE KEY-----"
PGP = b"-----BEGIN PGP PRIVATE KEY BLOCK-----\nYWJj\n-----END PGP PRIVATE KEY BLOCK-----"
CERT = b"-----BEGIN CERTIFICATE-----\nTUlJQg==\n-----END CERTIFICATE-----"
MARK = "[REDACTED_PEM]"


def test_block_split_across_chunks_is_redacted():
    chunks = [RSA[:17], RSA[17:48], RSA[48:]]
    result = ps.PemSpanScrubber().scrub(chunks)
    assert result["text"] == MARK
    assert len(result["spans"]) == 1
    assert result["spans"][0]["start"] == 0
    assert result["spans"][0]["end"] == len(RSA)
    assert result["spans"][0]["type"] == "RSA"


def test_openssh_private_key_marker_is_recognized():
    result = ps.PemSpanScrubber().scrub([OPENSSH])
    assert result["text"] == MARK
    assert result["spans"][0]["type"] == "OPENSSH"


def test_json_escaped_newlines_are_detected():
    escaped = RSA.replace(b"\n", b"\\n")
    result = ps.PemSpanScrubber().scrub([escaped])
    assert result["text"] == MARK
    assert result["spans"][0]["type"] == "RSA"


def test_pgp_and_certificate_blocks_are_both_redacted():
    result = ps.PemSpanScrubber().scrub([PGP + b"\n" + CERT])
    assert result["text"] == MARK + "\n" + MARK
    assert [span["type"] for span in result["spans"]] == ["PGP", "CERTIFICATE"]


def test_certificate_chain_block_is_recognized():
    result = ps.PemSpanScrubber().scrub([CERT])
    assert result["text"] == MARK
    assert result["spans"][0]["type"] == "CERTIFICATE"
    assert result["spans"][0]["start"] == 0


def test_nested_markers_are_treated_as_outer_block():
    nested = CERT.replace(b"\nTUlJQg==\n", b"\nTUlJQg==\n" + RSA + b"\n")
    result = ps.PemSpanScrubber().scrub([nested])
    assert result["text"] == MARK
    assert len(result["spans"]) == 1
    assert result["spans"][0]["type"] == "CERTIFICATE"
    assert result["spans"][0]["end"] == len(nested)


def test_unterminated_block_is_preserved_with_warning():
    truncated = b"-----BEGIN RSA PRIVATE KEY-----\nMIIE"
    result = ps.PemSpanScrubber().scrub([truncated])
    assert result["text"] == truncated.decode()
    assert result["spans"] == []
    assert "unterminated_block" in result["warnings"]


def test_allowlisted_fingerprint_is_preserved():
    allowed = {hashlib.sha256(RSA).hexdigest()}
    result = ps.PemSpanScrubber(allowed_fingerprints=allowed).scrub([RSA + b"\n" + CERT])
    assert result["text"].startswith(RSA.decode())
    assert MARK in result["text"]
    assert [span["type"] for span in result["spans"]] == ["CERTIFICATE"]


def test_mixed_case_markers_are_recognized():
    lower = RSA.lower()
    result = ps.PemSpanScrubber().scrub([lower])
    assert result["text"] == MARK
    assert result["spans"][0]["type"] == "RSA"


def test_surrounding_text_and_whitespace_are_unchanged():
    prefix = b"  line one\r\n"
    suffix = b"\r\n\tline two\n"
    result = ps.PemSpanScrubber().scrub([prefix + RSA + suffix])
    assert result["text"] == prefix.decode() + MARK + suffix.decode()
    assert result["spans"][0]["start"] == len(prefix)
    assert result["spans"][0]["end"] == len(prefix) + len(RSA)


def test_two_blocks_have_accurate_offsets():
    data = b"head\n" + RSA + b"\nmid\n" + CERT + b"\ntail"
    result = ps.PemSpanScrubber().scrub([data])
    assert len(result["spans"]) == 2
    first, second = result["spans"]
    assert data[first["start"]:first["end"]] == RSA
    assert data[second["start"]:second["end"]] == CERT


def test_oversized_unterminated_block_is_dropped_with_warning():
    oversized = b"-----BEGIN RSA PRIVATE KEY-----\n" + b"A" * 80
    result = ps.PemSpanScrubber(max_block_bytes=16).scrub([oversized])
    assert "A" * 80 not in result["text"]
    assert MARK in result["text"]
    assert "oversized_block" in result["warnings"]


def test_crlf_markers_are_recognized():
    crlf = RSA.replace(b"\n", b"\r\n")
    result = ps.PemSpanScrubber().scrub([b"x\r\n" + crlf + b"\r\ny"])
    assert result["text"] == "x\r\n" + MARK + "\r\ny"
    assert result["spans"][0]["start"] == 3


def test_consecutive_blocks_are_both_redacted():
    result = ps.PemSpanScrubber().scrub([RSA + RSA])
    assert result["text"] == MARK + MARK
    assert len(result["spans"]) == 2


def test_second_pass_is_idempotent():
    first = ps.PemSpanScrubber().scrub([b"before\n" + RSA + b"\nafter"])
    second = ps.PemSpanScrubber().scrub([first["text"].encode()])
    assert second["text"] == first["text"]
    assert second["spans"] == []
