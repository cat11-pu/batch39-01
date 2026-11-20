import hashlib
import re

_MARK = b"[REDACTED_PEM]"

_LABEL_TYPES = {
    b"RSA PRIVATE KEY": "RSA",
    b"EC PRIVATE KEY": "EC",
    b"OPENSSH PRIVATE KEY": "OPENSSH",
    b"PGP PRIVATE KEY BLOCK": "PGP",
    b"CERTIFICATE": "CERTIFICATE",
}

_BEGIN_RE = re.compile(
    rb"-----BEGIN (RSA PRIVATE KEY|EC PRIVATE KEY|OPENSSH PRIVATE KEY"
    rb"|PGP PRIVATE KEY BLOCK|CERTIFICATE)-----",
    re.IGNORECASE,
)

_END_RES = {
    label: re.compile(rb"-----END " + label + rb"-----", re.IGNORECASE)
    for label in _LABEL_TYPES
}


class PemSpanScrubber:
    def __init__(self, max_block_bytes=8192, allowed_fingerprints=()):
        self.max_block_bytes = max_block_bytes
        self.allowed_fingerprints = set(allowed_fingerprints)

    def scrub(self, chunks):
        data = b"".join(
            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            for chunk in chunks
        )
        out = []
        spans = []
        warnings = []
        pos = 0
        while True:
            begin = _BEGIN_RE.search(data, pos)
            if begin is None:
                out.append(data[pos:])
                break
            out.append(data[pos:begin.start()])
            label = begin.group(1).upper()
            end = _END_RES[label].search(data, begin.end())
            if end is not None and end.end() - begin.start() <= self.max_block_bytes:
                block = data[begin.start():end.end()]
                fingerprint = hashlib.sha256(block).hexdigest()
                if fingerprint in self.allowed_fingerprints:
                    out.append(block)
                else:
                    spans.append({
                        "start": begin.start(),
                        "end": end.end(),
                        "type": _LABEL_TYPES[label],
                    })
                    out.append(_MARK)
                pos = end.end()
                continue
            if end is not None or len(data) - begin.start() > self.max_block_bytes:
                warnings.append("oversized_block")
                out.append(_MARK)
                pos = end.end() if end is not None else len(data)
            else:
                warnings.append("unterminated_block")
                out.append(data[begin.start():])
                pos = len(data)
        text = b"".join(out).decode("utf-8", errors="surrogateescape")
        return {"text": text, "spans": spans, "warnings": warnings}
