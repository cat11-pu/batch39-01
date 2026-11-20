class DeviceError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class TrustedDeviceRegistry:
    def __init__(self, max_devices=5, ttl=30 * 86400, idle=7 * 86400, grace=300):
        pass

    def enroll(self, user_id, device_id, name, fingerprint, strong_auth, now):
        raise NotImplementedError

    def use(self, token, device_id, fingerprint, now, write=False, region=None):
        raise NotImplementedError

    def rotate(self, token, now):
        raise NotImplementedError

    def revoke(self, user_id, device_id):
        raise NotImplementedError

    def revoke_user(self, user_id):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
