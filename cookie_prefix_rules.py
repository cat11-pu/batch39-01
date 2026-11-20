class CookieError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CookiePrefixRules:
    def __init__(self, public_suffixes=(), max_count=50, max_size=4096):
        pass

    def parse(self, header_value):
        raise NotImplementedError

    def select(self, header_value, name, request_path="/"):
        raise NotImplementedError

    def set_cookie(self, name, value, path="/", domain=None, secure=False, httponly=False, samesite=None, max_age=None, expires=None):
        raise NotImplementedError

    def delete(self, name, path, domain=None):
        raise NotImplementedError
