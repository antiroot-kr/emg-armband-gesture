from collections import deque


class RollingSampleRate:
    """Estimate the receive rate from timestamps in a recent time window."""

    def __init__(self, window_seconds: float = 1.0):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = float(window_seconds)
        self._timestamps = deque()

    def record(self, timestamp: float) -> None:
        timestamp = float(timestamp)
        self._timestamps.append(timestamp)
        cutoff = timestamp - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    @property
    def hz(self):
        if len(self._timestamps) < 2:
            return None
        elapsed = self._timestamps[-1] - self._timestamps[0]
        if elapsed <= 0:
            return None
        return (len(self._timestamps) - 1) / elapsed

    def reset(self) -> None:
        self._timestamps.clear()
