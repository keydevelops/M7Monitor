import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import constants


@dataclass
class HeartRateSample:
    value: int
    timestamp: datetime
    source: str


@dataclass
class BandState:
    status: str = "starting"
    device_name: Optional[str] = None
    device_address: Optional[str] = None
    auth_method: Optional[str] = None
    newest_hr: Optional[HeartRateSample] = None
    samples: list[HeartRateSample] = field(default_factory=list)
    last_poll: Optional[datetime] = None
    last_packet: Optional[str] = None
    last_error: Optional[str] = None
    services: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def set_status(self, status: str, error: Optional[str] = None):
        with self.lock:
            self.status = status
            if error:
                self.last_error = error
        print(f"[state] {status}" + (f": {error}" if error else ""))

    def update_hr(self, value: Optional[int], source: str, timestamp: Optional[datetime] = None):
        if value is None or value <= 0 or value >= 255:
            return
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        sample = HeartRateSample(value=value, timestamp=timestamp, source=source)
        with self.lock:
            if self.newest_hr is None or sample.timestamp >= self.newest_hr.timestamp:
                self.newest_hr = sample
                constants.debug(f"[HR] {value} bpm [{source}] {timestamp.isoformat()}")
            self.samples.append(sample)
            self.samples = self.samples[-120:]

    def remember_packet(self, source: str, data: bytes):
        with self.lock:
            self.last_packet = f"{source}: {data.hex()}"

    def as_dict(self):
        with self.lock:
            now = datetime.now(timezone.utc)
            newest = None
            stale = True
            if self.newest_hr:
                age = max(0, int((now - self.newest_hr.timestamp).total_seconds()))
                stale = age > constants.STALE_AFTER_SECONDS
                newest = {
                    "value": self.newest_hr.value,
                    "timestamp": self.newest_hr.timestamp.isoformat(),
                    "source": self.newest_hr.source,
                    "age_seconds": age,
                    "stale": stale,
                }

            data = {
                "status": self.status,
                "heart_rate": newest,
                "stale": stale,
                "last_error": self.last_error,
                "settings": {
                    "debug": constants.DEBUG,
                    "disableColors": constants.DISABLE_COLORS,
                },
            }
            if constants.DEBUG:
                data.update(
                    {
                        "device_name": self.device_name,
                        "device_address": self.device_address,
                        "auth_method": self.auth_method,
                        "last_poll": self.last_poll.isoformat() if self.last_poll else None,
                        "last_packet": self.last_packet,
                        "services": self.services,
                        "samples": [
                            {
                                "value": s.value,
                                "timestamp": s.timestamp.isoformat(),
                                "source": s.source,
                            }
                            for s in self.samples[-30:]
                        ],
                    }
                )
            return data
