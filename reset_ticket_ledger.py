class ResetTicketError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ResetTicketVault:
    def __init__(self, ttl=600, max_token_len=128):
        pass

    def issue(self, user_id, device_id, now):
        raise NotImplementedError

    def redeem(self, token, user_id, device_id, now):
        raise NotImplementedError

    def revoke_all(self, user_id):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
