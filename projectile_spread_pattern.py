import math
import random


class SpreadError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ProjectileSpreadPattern:
    MOVING_FACTOR = 1.5
    JUMPING_FACTOR = 2.0
    CROUCH_FACTOR = 0.75
    CROUCH_RECOVERY_FACTOR = 1.5
    MIN_SPREAD = 0.05
    BURST_GAP_SECONDS = 1.0
    RECOIL_PATTERN = (
        (0.00, 0.40),
        (0.08, 0.45),
        (-0.08, 0.50),
        (0.12, 0.45),
        (-0.12, 0.55),
    )

    def __init__(self, first_shot=0.0, per_shot=0.5, recovery=2.0, max_spread=5.0, ads_scale=0.5, pellets=1):
        if first_shot < 0.0 or per_shot < 0.0:
            raise SpreadError("invalid_spread")
        if recovery <= 0.0 or max_spread <= 0.0:
            raise SpreadError("invalid_spread")
        if not 0.0 < ads_scale <= 1.0:
            raise SpreadError("invalid_ads_scale")
        if pellets < 1:
            raise SpreadError("invalid_pellets")
        self.first_shot = float(first_shot)
        self.per_shot = float(per_shot)
        self.recovery = float(recovery)
        self.max_spread = float(max_spread)
        self.ads_scale = float(ads_scale)
        self.pellets = int(pellets)
        self._bloom = 0.0
        self._shot_count = 0
        self._primed = False

    def fire(self, shots=1, seed=0, ads=False, moving=False, jumping=False, crouching=False, mirror=False):
        if shots < 1:
            raise SpreadError("invalid_shots")

        if self._primed:
            rate = self.recovery * (self.CROUCH_RECOVERY_FACTOR if crouching else 1.0)
            self._bloom = max(0.0, self._bloom - rate * self.BURST_GAP_SECONDS)
            if self._bloom == 0.0:
                self._primed = False

        rng = random.Random(seed)
        cap = self.max_spread * (self.ads_scale if ads else 1.0)
        factor = 1.0
        if moving:
            factor *= self.MOVING_FACTOR
        if jumping:
            factor *= self.JUMPING_FACTOR
        if crouching:
            factor *= self.CROUCH_FACTOR
        if ads:
            factor *= self.ads_scale

        spreads = []
        directions = []
        recoils = []

        for _ in range(shots):
            if not self._primed:
                self._bloom = self.first_shot
                self._primed = True
            else:
                self._bloom = min(self.max_spread, self._bloom + self.per_shot)

            effective = max(self.MIN_SPREAD, self._bloom) * factor
            effective = min(cap, effective)
            spreads.append(effective)

            for _pellet in range(self.pellets):
                directions.append(self._direction(rng, effective))

            horizontal, vertical = self.RECOIL_PATTERN[self._shot_count % len(self.RECOIL_PATTERN)]
            if mirror:
                horizontal = -horizontal
            recoils.append((horizontal, vertical))
            self._shot_count += 1

        recovery_rate = self.recovery * (self.CROUCH_RECOVERY_FACTOR if crouching else 1.0)
        recovery_time = self._bloom / recovery_rate

        return {
            "spread": spreads,
            "directions": directions,
            "recoil": recoils,
            "recovery_time": recovery_time,
        }

    @staticmethod
    def _direction(rng, spread):
        angle = rng.uniform(0.0, math.tau)
        radius = math.sqrt(rng.random()) * spread
        yaw = math.cos(angle) * radius
        pitch = math.sin(angle) * radius
        return (
            math.sin(yaw),
            math.sin(pitch),
            math.cos(yaw) * math.cos(pitch),
        )
