import os
import dotenv
from pathlib import Path

# def _load_env():
#     env_path = Path(__file__).parent.parent / ".env"
#     if env_path.exists():
#         with open(env_path, "r", encoding="utf-8") as f:
#             for line in f:
#                 line = line.strip()
#                 if line and not line.startswith("#") and "=" in line:
#                     key, value = line.split("=", 1)
#                     os.environ.setdefault(key.strip(), value.strip())


# _load_env()

# Just settings
TARGET_NAME_KEY = os.getenv("TARGET_NAME_KEY", "Smart Band")
AUTH_KEY = os.getenv("AUTH_KEY", "e4c0e04a910e41bde0ab1a6e78885370")
OVERLAY_HOST = os.getenv("OVERLAY_HOST", "127.0.0.1")
OVERLAY_PORT = int(os.getenv("OVERLAY_PORT", "8765"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "61"))
INITIAL_FETCH_MINUTES = int(os.getenv("INITIAL_FETCH_MINUTES", "15"))
STALE_AFTER_SECONDS = int(os.getenv("STALE_AFTER_SECONDS", "180"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
DISABLE_COLORS = os.getenv("DISABLE_COLORS", "False").lower() in ("true", "1", "yes")


# Mi Band 7 Characteristics
UUID_RAW_SENSOR_CONTROL = "00000001-0000-3512-2118-0009af100700"
UUID_RAW_SENSOR_DATA = "00000002-0000-3512-2118-0009af100700"
UUID_FETCH = "00000004-0000-3512-2118-0009af100700"
UUID_ACTIVITY_DATA = "00000005-0000-3512-2118-0009af100700"
UUID_CHUNKED_WRITE = "00000016-0000-3512-2118-0009af100700"
UUID_CHUNKED_READ = "00000017-0000-3512-2118-0009af100700"
UUID_HEARTRATE = "00002a37-0000-1000-8000-00805f9b34fb"
UUID_HEARTRATE_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"

# Magic protocol bytes :sparkles: (<- just pretend that it's an emoji)
CHUNK_ENDPOINT_AUTH = 0x0082
FETCH_FROM_DATE = 0x01
FETCH_BEGIN_TRANSFER = 0x02
FETCH_ACTIVITY_DATA = 0x01
FETCH_ACK_NO_DROP = bytes([0x03, 0x09])

# Lonely debug-print function :(
def debug(message: str):
    if DEBUG:
        print(message)
