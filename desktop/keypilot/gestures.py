from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GestureRecognizer:
    double_tap_seconds: float
    hold_seconds: float
    immediate_tap: bool = False
    _is_down: bool = False
    _down_at: Optional[float] = None
    _pending_tap_at: Optional[float] = None

    def key_down(self, now: float) -> None:
        if self._is_down:
            return
        self._is_down = True
        self._down_at = now

    def key_up(self, now: float) -> Optional[str]:
        if not self._is_down or self._down_at is None:
            return None

        self._is_down = False
        held_for = now - self._down_at
        self._down_at = None

        if held_for >= self.hold_seconds:
            self._pending_tap_at = None
            return "hold"

        if self.immediate_tap:
            self._pending_tap_at = None
            return "tap"

        if self._pending_tap_at is not None:
            if now - self._pending_tap_at <= self.double_tap_seconds:
                self._pending_tap_at = None
                return "double_tap"

        self._pending_tap_at = now
        return None

    def poll(self, now: float) -> Optional[str]:
        if self._pending_tap_at is None:
            return None
        if self._is_down:
            return None
        if now - self._pending_tap_at < self.double_tap_seconds:
            return None
        self._pending_tap_at = None
        return "tap"
