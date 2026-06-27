import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec

from . import constants
from .crypto import aes_cbc_encrypt, aes_ecb_encrypt, watch_date_bytes
from .models import BandState


class MiBand7Client:
    def __init__(self, state: BandState):
        self.state = state
        self.client: Optional[BleakClient] = None
        self.chars = {}
        self.char_props = {}
        self.handle = 0
        self.notified = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.auth_queue: Optional[asyncio.Queue] = None
        self.fetch_queue: Optional[asyncio.Queue] = None
        self.activity_buffer = bytearray()
        self.activity_start: Optional[datetime] = None
        self.last_activity_timestamp: Optional[datetime] = None

    async def run_forever(self, stop_event: asyncio.Event):
        self.loop = asyncio.get_running_loop()
        while not stop_event.is_set():
            try:
                await self._connect_session(stop_event)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.state.set_status("error", repr(e))
            finally:
                await self._disconnect()
            if not stop_event.is_set():
                self.state.set_status("disconnected")
                await asyncio.sleep(5)

    async def _connect_session(self, stop_event: asyncio.Event):
        device = await self._scan(stop_event)
        if device is None:
            return

        with self.state.lock:
            self.state.device_name = device.name
            self.state.device_address = device.address

        self.state.set_status("connecting")
        async with BleakClient(device, timeout=30.0) as client:
            self.client = client
            constants.debug(f"[ble] connected: {device.address} {device.name}")
            await asyncio.sleep(1)
            self._discover_chars()

            self.state.set_status("authenticating")
            authed = await self._authenticate()
            if not authed:
                raise RuntimeError("authentication failed")

            if self._has_char(constants.UUID_CURRENT_TIME):
                try:
                    val = await self.client.read_gatt_char(constants.UUID_CURRENT_TIME)
                    constants.debug(f"[current time] {val.hex()}")
                except Exception as e:
                    constants.debug(f"[current time error] {e}")

            self.state.set_status("connected")
            await self._start_heart_sources()
            self.state.set_status("polling")

            while client.is_connected and not stop_event.is_set():
                await self._poll_activity_recent()
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=constants.POLL_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    pass

    async def _scan(self, stop_event: asyncio.Event):
        attempt = 0
        while not stop_event.is_set():
            attempt += 1
            self.state.set_status("scanning")
            constants.debug(f"[scan] attempt {attempt}")
            try:
                devices = await BleakScanner.discover(timeout=5.0)
                for device in devices:
                    if device.name and constants.TARGET_NAME_KEY in device.name:
                        constants.debug(f"[scan] found {device.address} {device.name}")
                        return device
            except Exception as e:
                self.state.set_status("scan_error", repr(e))
            await asyncio.sleep(2)
        return None

    def _discover_chars(self):
        self.chars.clear()
        self.char_props.clear()
        services = []
        for service in self.client.services:
            services.append(str(service.uuid).lower())
            for char in service.characteristics:
                uuid = str(char.uuid).lower()
                self.chars[uuid] = char
                self.char_props[uuid] = set(char.properties)
                constants.debug(f"[char] {uuid} props={','.join(char.properties)}")
        with self.state.lock:
            self.state.services = services

    def _has_char(self, uuid: str, prop: Optional[str] = None) -> bool:
        uuid = uuid.lower()
        if uuid not in self.chars:
            return False
        if prop is None:
            return True
        return prop in self.char_props.get(uuid, set())

    async def _write_char(self, uuid: str, data: bytes, response: Optional[bool] = None):
        uuid = uuid.lower()
        if response is None:
            props = self.char_props.get(uuid, set())
            response = "write" in props and "write-without-response" not in props
        constants.debug(f"[write] {uuid} <- {data.hex()} response={response}")
        await self.client.write_gatt_char(uuid, data, response=response)

    async def _notify(self, uuid: str, callback) -> bool:
        uuid = uuid.lower()
        if uuid in self.notified:
            return True
        if not self._has_char(uuid, "notify"):
            return False
        await self.client.start_notify(uuid, callback)
        self.notified.add(uuid)
        constants.debug(f"[notify] subscribed {uuid}")
        return True

    async def _authenticate(self) -> bool:
        if self._has_char(constants.UUID_CHUNKED_WRITE) and self._has_char(constants.UUID_CHUNKED_READ, "notify"):
            try:
                ok = await self._authenticate_chunked()
                if ok:
                    with self.state.lock:
                        self.state.auth_method = "chunked-2021"
                    return True
            except Exception as e:
                constants.debug(f"auth_chunked_error: {repr(e)}")
            
            # If chunked failed, wait 1 second to let watch clear state and try legacy fallback
            await asyncio.sleep(1.0)
                
        if self._has_char(constants.UUID_RAW_SENSOR_CONTROL, "notify"):
            ok = await self._authenticate_legacy()
            if ok:
                with self.state.lock:
                    self.state.auth_method = "legacy-raw-sensor"
            return ok

        return False

    async def _authenticate_chunked(self) -> bool:
        self.auth_queue = asyncio.Queue()

        def on_chunked_read(sender, data: bytearray):
            raw = bytes(data)
            self.state.remember_packet("chunked_read", raw)
            if self.loop and self.auth_queue:
                self.loop.call_soon_threadsafe(self.auth_queue.put_nowait, raw)

        await self._notify(constants.UUID_CHUNKED_READ, on_chunked_read)

        private_key = ec.generate_private_key(ec.SECP192R1(), default_backend())
        numbers = private_key.public_key().public_numbers()
        public_key = numbers.x.to_bytes(24, "big") + numbers.y.to_bytes(24, "big")
        initial = bytes([0x04, 0x02, 0x00, 0x02]) + public_key
        constants.debug("[auth] sending chunked public key")
        await self._write_chunked(constants.CHUNK_ENDPOINT_AUTH, initial)

        buffer = bytearray()
        expected = None
        last_seq = -1

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                timeout = max(0.1, deadline - time.monotonic())
                raw = await asyncio.wait_for(self.auth_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                constants.debug("[auth] timeout waiting for packet")
                return False

            constants.debug(f"[auth<-] {raw.hex()}")
            if len(raw) < 5 or raw[0] != 0x03:
                continue

            seq = raw[4]

            # Success packet: raw[0]=0x03, seq=0, raw[9:11]=auth_endpoint, raw[11:14]=10 05 01
            if (
                seq == 0
                and len(raw) >= 14
                and raw[9] == (constants.CHUNK_ENDPOINT_AUTH & 0xFF)
                and raw[10] == (constants.CHUNK_ENDPOINT_AUTH >> 8)
                and raw[11:14] == bytes([0x10, 0x05, 0x01])
            ):
                constants.debug("[auth] Successfully authenticated (received 10 05 01)")
                return True

            # Challenge start packet: raw[0]=0x03, seq=0, raw[9:11]=auth_endpoint, raw[11:14]=10 04 01
            if (
                seq == 0
                and len(raw) >= 14
                and raw[9] == (constants.CHUNK_ENDPOINT_AUTH & 0xFF)
                and raw[10] == (constants.CHUNK_ENDPOINT_AUTH >> 8)
                and raw[11:14] == bytes([0x10, 0x04, 0x01])
            ):
                expected = max(0, raw[5] - 3)
                buffer.clear()
                buffer.extend(raw[14:])
                last_seq = 0
            elif seq > 0:
                if seq != last_seq + 1:
                    constants.debug(f"[auth] Unexpected sequence number: {seq}, expected {last_seq + 1}")
                    return False
                buffer.extend(raw[5:])
                last_seq = seq
            else:
                continue

            if expected is not None and len(buffer) >= expected:
                payload = bytes(buffer[:expected])
                if len(payload) < 64:
                    constants.debug(f"[auth] Challenge payload too short: {len(payload)}")
                    return False

                remote_random = payload[:16]
                remote_public_raw = payload[16:64]
                remote_public_numbers = ec.EllipticCurvePublicNumbers(
                    int.from_bytes(remote_public_raw[:24], "big"),
                    int.from_bytes(remote_public_raw[24:], "big"),
                    ec.SECP192R1(),
                )
                remote_public_key = remote_public_numbers.public_key(default_backend())
                shared_secret = private_key.exchange(ec.ECDH(), remote_public_key)
                if len(shared_secret) < 24:
                    shared_secret = shared_secret.rjust(24, b"\x00")

                auth_key = bytes.fromhex(constants.AUTH_KEY)
                session_key = bytes(shared_secret[8 + i] ^ auth_key[i] for i in range(16))
                out1 = aes_cbc_encrypt(auth_key, remote_random)
                out2 = aes_cbc_encrypt(session_key, remote_random)
                second = bytes([0x05]) + out1 + out2

                constants.debug("[auth] sending chunked proof")
                await self._write_chunked(constants.CHUNK_ENDPOINT_AUTH, second)

                # Reset challenge reassembly state, wait for success packet
                buffer.clear()
                expected = None
                last_seq = -1

    async def _authenticate_legacy(self) -> bool:
        auth_queue = asyncio.Queue()

        def on_auth(sender, data: bytearray):
            raw = bytes(data)
            self.state.remember_packet("legacy_auth", raw)
            if self.loop:
                self.loop.call_soon_threadsafe(auth_queue.put_nowait, raw)

        await self._notify(constants.UUID_RAW_SENSOR_CONTROL, on_auth)
        auth_key = bytes.fromhex(constants.AUTH_KEY)
        commands = [
            b"\x04\x01",
            b"\x04\x02",
            b"\x05\x01",
            b"\x01\x00\x02",
            b"\x02\x00\x02",
            b"\x01\x01\x02" + auth_key,
            b"\x01\x00" + auth_key,
        ]
        encrypted = None
        for cmd in commands:
            await self._write_char(constants.UUID_RAW_SENSOR_CONTROL, cmd, response=True)
            try:
                raw = await asyncio.wait_for(auth_queue.get(), timeout=3)
            except asyncio.TimeoutError:
                continue
            constants.debug(f"[legacy auth<-] {raw.hex()}")
            if raw[:3] == b"\x10\x02\x01":
                return True
            if len(raw) >= 19 and (raw[:3] == b"\x10\x01\x01" or raw[:2] == b"\x10\x02"):
                encrypted = aes_ecb_encrypt(auth_key, raw[3:19])
                break

        if encrypted:
            for prefix in (b"\x03\x01", b"\x03\x00"):
                await self._write_char(constants.UUID_RAW_SENSOR_CONTROL, prefix + encrypted, response=True)
                try:
                    raw = await asyncio.wait_for(auth_queue.get(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                constants.debug(f"[legacy auth<-] {raw.hex()}")
                if raw[:3] == b"\x10\x02\x01":
                    return True
        return False

    async def _write_chunked(self, endpoint: int, payload: bytes, base_flags: int = 0):
        remaining = len(payload)
        count = 0
        header_size = 11
        mtu = 23
        while remaining > 0:
            max_chunk = mtu - 3 - header_size
            copy_bytes = min(remaining, max_chunk)
            flags = base_flags
            chunk = bytearray(copy_bytes + header_size)
            if count == 0:
                data_len = len(payload) - flags
                chunk[5] = data_len & 0xFF
                chunk[6] = (data_len >> 8) & 0xFF
                chunk[7] = (data_len >> 16) & 0xFF
                chunk[8] = (data_len >> 24) & 0xFF
                chunk[9] = endpoint & 0xFF
                chunk[10] = (endpoint >> 8) & 0xFF
                flags |= 0x01
            if remaining <= max_chunk:
                flags |= 0x06
            chunk[0] = 0x03
            chunk[1] = flags
            chunk[2] = 0x00
            chunk[3] = self.handle & 0xFF
            chunk[4] = count & 0xFF
            start = len(payload) - remaining
            chunk[header_size:] = payload[start:start + copy_bytes]
            await self._write_char(constants.UUID_CHUNKED_WRITE, bytes(chunk))
            remaining -= copy_bytes
            header_size = 5
            count += 1
            await asyncio.sleep(0.05)
        self.handle = (self.handle + 1) & 0xFF

    async def _start_heart_sources(self):
        if self._has_char(constants.UUID_HEARTRATE, "notify"):
            await self._notify(constants.UUID_HEARTRATE, self._on_standard_hr)
        if self._has_char(constants.UUID_HEARTRATE_CONTROL):
            for cmd in (b"\x15\x02\x00", b"\x15\x01\x00", b"\x15\x01\x01"):
                try:
                    await self._write_char(constants.UUID_HEARTRATE_CONTROL, cmd)
                    await asyncio.sleep(0.1)
                except Exception as e:
                    constants.debug(f"[hr ctrl] {e}")

        if self._has_char(constants.UUID_FETCH, "notify"):
            await self._notify(constants.UUID_FETCH, self._on_fetch)
        if self._has_char(constants.UUID_ACTIVITY_DATA, "notify"):
            await self._notify(constants.UUID_ACTIVITY_DATA, self._on_activity_data)

    def _on_standard_hr(self, sender, data: bytearray):
        raw = bytes(data)
        self.state.remember_packet("0x2a37", raw)
        if len(raw) < 2:
            return
        flags = raw[0]
        if flags & 0x01:
            if len(raw) >= 3:
                hr = raw[1] | (raw[2] << 8)
            else:
                return
        else:
            hr = raw[1]
        self.state.update_hr(hr, "0x2a37-live")

    def _on_fetch(self, sender, data: bytearray):
        raw = bytes(data)
        self.state.remember_packet("fetch", raw)
        if self.loop and self.fetch_queue:
            self.loop.call_soon_threadsafe(self.fetch_queue.put_nowait, raw)

    def _on_activity_data(self, sender, data: bytearray):
        raw = bytes(data)
        self.state.remember_packet("activity", raw)
        if len(raw) <= 1:
            return
        data_without_batch = raw[1:]
        self.activity_buffer.extend(data_without_batch)
        self._parse_activity_records(data_without_batch, self.activity_start, "activity-notify")

    async def _poll_activity_recent(self):
        if not (self._has_char(constants.UUID_FETCH) and self._has_char(constants.UUID_ACTIVITY_DATA, "notify")):
            return

        since = self.last_activity_timestamp + timedelta(seconds=1) if self.last_activity_timestamp else datetime.now(timezone.utc) - timedelta(minutes=constants.INITIAL_FETCH_MINUTES)
        for _ in range(4):
            next_since = await self._fetch_activity_since(since)
            if not next_since or next_since >= datetime.now(timezone.utc):
                break
            since = next_since

    async def _fetch_activity_since(self, since: datetime) -> Optional[datetime]:
        self.fetch_queue = asyncio.Queue()
        self.activity_buffer = bytearray()
        self.activity_start = None
        self.state.last_poll = datetime.now(timezone.utc)

        watch_date = watch_date_bytes(since)
        command = bytes([constants.FETCH_FROM_DATE, constants.FETCH_ACTIVITY_DATA]) + watch_date + b"\x00\x00"
        constants.debug(f"[fetch] since={since.isoformat()} cmd={command.hex()}")
        await self._write_char(constants.UUID_FETCH, command, response=False)

        ready = await self._wait_fetch_ready(timeout=10)
        if not ready:
            constants.debug("[fetch] not ready")
            return None

        await self._write_char(constants.UUID_FETCH, bytes([constants.FETCH_BEGIN_TRANSFER]), response=False)
        done = await self._wait_fetch_done(timeout=35)
        if not done:
            constants.debug("[fetch] transfer timeout")
            return None

        records = len(self.activity_buffer) // 8
        if self.activity_start and records:
            next_time = self.activity_start + timedelta(minutes=records)
            self.last_activity_timestamp = max(self.last_activity_timestamp or self.activity_start, next_time)
            return next_time
        return None

    async def _wait_fetch_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.fetch_queue.get(), timeout=max(0.1, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                return False
            constants.debug(f"[fetch<-] {raw.hex()}")
            if raw[:3] == b"\x10\x01\x01" and len(raw) >= 15:
                year = int.from_bytes(raw[7:9], "little")
                month = raw[9]
                day = raw[10]
                hour = raw[11]
                minute = raw[12] - (raw[14] * 15 if len(raw) > 14 else 0)
                second = raw[13]
                self.activity_start = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
                return True
            if raw[:3] == b"\x10\x01\x32":
                return False
        return False

    async def _wait_fetch_done(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.fetch_queue.get(), timeout=max(0.1, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                return False
            constants.debug(f"[fetch<-] {raw.hex()}")
            if raw[:3] == b"\x10\x02\x01":
                await self._write_char(constants.UUID_FETCH, constants.FETCH_ACK_NO_DROP, response=False)
                self._parse_activity_records(bytes(self.activity_buffer), self.activity_start, "activity-fetch")
                return True
            if raw[:3] == b"\x10\x02\x32":
                return False
        return False

    def _parse_activity_records(self, data: bytes, start: Optional[datetime], source: str):
        stride = 8
        if len(data) < stride:
            return
        if len(data) % stride != 0:
            data = data[: len(data) - (len(data) % stride)]
        for i in range(0, len(data), stride):
            record = data[i:i + stride]
            hr = record[3]
            timestamp = start + timedelta(minutes=i // stride) if start else datetime.now(timezone.utc)
            self.state.update_hr(hr if hr != 255 else None, source, timestamp)

    async def _disconnect(self):
        if self.client:
            for uuid in list(self.notified):
                try:
                    await self.client.stop_notify(uuid)
                except Exception:
                    pass
            self.notified.clear()
            if self.client.is_connected:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
            self.client = None
