"""SFT1: bounded, length-prefixed frames over an authenticated TLS stream."""
import asyncio
import enum
import json
import struct
from dataclasses import dataclass, field

HEADER = struct.Struct("!4sBBHIII")
MAGIC = b"SFT1"
VERSION = 1
MAX_META = 65536
CHUNK = 65536


class Kind(enum.IntEnum):
    HELLO = 1
    WELCOME = 2
    LIST = 10
    LIST_RESULT = 11
    MKDIR = 12
    OK = 13
    PUT_INIT = 20
    GET_INIT = 21
    READY = 22
    DATA = 23
    ACK = 24
    FINISH = 25
    RESULT = 26
    READ = 27
    PAUSE = 30
    RESUME = 31
    CANCEL = 32
    PING = 40
    PONG = 41
    ERROR = 255


class Fault(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Frame:
    kind: Kind
    request: int = 0
    meta: dict = field(default_factory=dict)
    data: bytes = b""

    def encode(self):
        raw = json.dumps(self.meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_META or len(self.data) > CHUNK:
            raise Fault("PROTOCOL", "报文超过长度上限")
        return HEADER.pack(MAGIC, VERSION, self.kind, 0, self.request, len(raw), len(self.data)) + raw + self.data


async def read_frame(reader, idle_timeout=45, partial_timeout=15):
    first = await asyncio.wait_for(reader.readexactly(1), idle_timeout)
    async with asyncio.timeout(partial_timeout):
        raw = first + await reader.readexactly(HEADER.size - 1)
        magic, version, kind, flags, request, mlen, dlen = HEADER.unpack(raw)
        if magic != MAGIC or version != VERSION or flags or mlen > MAX_META or dlen > CHUNK:
            raise Fault("PROTOCOL", "无效报头或报文长度")
        try:
            kind = Kind(kind)
            meta = json.loads(await reader.readexactly(mlen), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise Fault("PROTOCOL", "无效消息类型或JSON") from exc
        if not isinstance(meta, dict):
            raise Fault("PROTOCOL", "元数据必须是对象")
        return Frame(kind, request, meta, await reader.readexactly(dlen))


def string(meta, key, maximum=4096):
    value = meta.get(key)
    if not isinstance(value, str) or not value or len(value.encode()) > maximum or "\0" in value:
        raise Fault("INPUT", f"无效字段 {key}")
    return value


def integer(meta, key, minimum=0, maximum=2**63-1):
    value = meta.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise Fault("INPUT", f"无效字段 {key}")
    return value
