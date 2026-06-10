import asyncio
import signal

from m7monitor import constants
from m7monitor.models import BandState
from m7monitor.client import MiBand7Client
from m7monitor.server import OverlayServer


async def run():
    if len(constants.AUTH_KEY) != 32:
        raise ValueError("AUTH_KEY should be 32 hex symbols")

    state = BandState()
    server = OverlayServer(state)
    server.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def stop():
        print("\n[stop] shutting down...")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, stop)
        loop.add_signal_handler(signal.SIGTERM, stop)
    except NotImplementedError:
        pass

    client = MiBand7Client(state)
    try:
        await client.run_forever(stop_event)
    except KeyboardInterrupt:
        print("\n[stop] KeyboardInterrupt received, shutting down...")
        stop_event.set()
    finally:
        await client._disconnect()
        server.stop()

if __name__ == "__main__":
    asyncio.run(run())