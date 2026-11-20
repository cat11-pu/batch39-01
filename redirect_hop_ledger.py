from urllib.parse import unquote, urljoin, urlsplit


class RedirectHopError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_DEFAULT_HTTPS_PORT = 443
_REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))
_METHOD_PRESERVING_STATUSES = frozenset((307, 308))
_SAFE_METHODS = frozenset(("GET", "HEAD"))


class RedirectHopLedger:
    def __init__(self, allowed_hosts, allowed_ports=(443,), max_hops=8):
        self._allowed_hosts = frozenset(self._normalize_host(host) for host in allowed_hosts)
        self._allowed_ports = frozenset(int(port) for port in allowed_ports)
        self._max_hops = int(max_hops)

    @staticmethod
    def _normalize_host(host):
        return unquote(host or "").strip().lower().rstrip(".")

    def _check_url(self, url, is_start):
        if "\\" in url:
            raise RedirectHopError("unsafe_redirect")
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme != "https":
            if scheme == "http" and not is_start:
                raise RedirectHopError("downgrade")
            raise RedirectHopError("unsafe_redirect")
        if parts.username is not None or parts.password is not None:
            raise RedirectHopError("unsafe_redirect")
        if self._normalize_host(parts.hostname) not in self._allowed_hosts:
            raise RedirectHopError("unsafe_redirect")
        port = parts.port
        effective_port = port if port is not None else _DEFAULT_HTTPS_PORT
        if effective_port != _DEFAULT_HTTPS_PORT and effective_port not in self._allowed_ports:
            raise RedirectHopError("unsafe_redirect")

    def resolve(self, start_url, fetch, method="GET"):
        self._check_url(start_url, is_start=True)
        hops = []
        visited = {start_url}
        url = start_url
        current_method = method
        reason = None
        while True:
            response = fetch(url, current_method) or {}
            status = response.get("status")
            hops.append({"url": url, "method": current_method, "status": status})
            if status not in _REDIRECT_STATUSES:
                reason = "ok" if len(hops) > 1 else "not_redirect"
                break
            location = response.get("location")
            if location is None:
                reason = "empty_location"
                break
            if any(ord(char) < 0x20 or ord(char) == 0x7F for char in location):
                raise RedirectHopError("invalid_location")
            location = location.strip()
            if not location:
                reason = "empty_location"
                break
            try:
                target = urljoin(url, location)
                self._check_url(target, is_start=False)
            except RedirectHopError:
                raise
            except ValueError:
                reason = "invalid_location"
                break
            if target in visited:
                reason = "loop"
                break
            if len(hops) >= self._max_hops:
                reason = "max_hops"
                break
            if status not in _METHOD_PRESERVING_STATUSES and current_method.upper() not in _SAFE_METHODS:
                current_method = "GET"
            visited.add(target)
            url = target
        return {"final_url": hops[-1]["url"], "hops": hops, "reason": reason}
