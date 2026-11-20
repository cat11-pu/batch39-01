class FormSegmentError(ValueError):
    def __init__(self, code, field=None):
        super().__init__(code)
        self.code = code
        self.field = field


class FormSegmentFence:
    def __init__(self, max_segments=100, max_segment_bytes=1024 * 1024, max_header_lines=20, max_total_bytes=8 * 1024 * 1024, max_nesting=1):
        pass

    def parse(self, body, content_type):
        raise NotImplementedError
