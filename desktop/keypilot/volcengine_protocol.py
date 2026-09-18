"""Binary protocol used by the Volcengine v3 bidirectional TTS service."""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from enum import IntEnum


class MsgType(IntEnum):
    FULL_CLIENT_REQUEST = 0b0001
    AUDIO_ONLY_CLIENT = 0b0010
    FULL_SERVER_RESPONSE = 0b1001
    AUDIO_ONLY_SERVER = 0b1011
    ERROR = 0b1111


class Flag(IntEnum):
    NO_SEQUENCE = 0
    POSITIVE_SEQUENCE = 0b0001
    NEGATIVE_SEQUENCE = 0b0011
    WITH_EVENT = 0b0100


class Event(IntEnum):
    START_CONNECTION = 1
    FINISH_CONNECTION = 2
    CONNECTION_STARTED = 50
    CONNECTION_FAILED = 51
    CONNECTION_FINISHED = 52
    START_SESSION = 100
    CANCEL_SESSION = 101
    FINISH_SESSION = 102
    SESSION_STARTED = 150
    SESSION_CANCELED = 151
    SESSION_FINISHED = 152
    SESSION_FAILED = 153
    TASK_REQUEST = 200


_CONNECTION_EVENTS = {
    Event.START_CONNECTION,
    Event.FINISH_CONNECTION,
    Event.CONNECTION_STARTED,
    Event.CONNECTION_FAILED,
    Event.CONNECTION_FINISHED,
}


@dataclass
class Message:
    msg_type: MsgType
    flag: Flag = Flag.NO_SEQUENCE
    event: Event | int = 0
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0
    payload: bytes = b""

    def encode(self) -> bytes:
        out = io.BytesIO()
        out.write(bytes([0x11, (int(self.msg_type) << 4) | int(self.flag), 0x10, 0x00]))
        if self.flag == Flag.WITH_EVENT:
            out.write(struct.pack(">i", int(self.event)))
            if self.event not in _CONNECTION_EVENTS:
                session = self.session_id.encode("utf-8")
                out.write(struct.pack(">I", len(session)))
                out.write(session)
        if self.flag in (Flag.POSITIVE_SEQUENCE, Flag.NEGATIVE_SEQUENCE):
            out.write(struct.pack(">i", self.sequence))
        out.write(struct.pack(">I", len(self.payload)))
        out.write(self.payload)
        return out.getvalue()

    @classmethod
    def decode(cls, data: bytes) -> "Message":
        if len(data) < 4:
            raise ValueError("火山引擎响应短于协议头。")
        stream = io.BytesIO(data)
        header_size = (stream.read(1)[0] & 0x0F) * 4
        type_and_flag = stream.read(1)[0]
        msg_type = MsgType(type_and_flag >> 4)
        flag = Flag(type_and_flag & 0x0F)
        stream.read(1)
        stream.read(max(1, header_size - 3))
        message = cls(msg_type=msg_type, flag=flag)

        if msg_type == MsgType.ERROR:
            raw = stream.read(4)
            if len(raw) == 4:
                message.error_code = struct.unpack(">I", raw)[0]
        elif flag in (Flag.POSITIVE_SEQUENCE, Flag.NEGATIVE_SEQUENCE):
            message.sequence = struct.unpack(">i", stream.read(4))[0]

        if flag == Flag.WITH_EVENT:
            event_value = struct.unpack(">i", stream.read(4))[0]
            try:
                message.event = Event(event_value)
            except ValueError:
                message.event = event_value
            if message.event not in _CONNECTION_EVENTS:
                message.session_id = _read_string(stream)
            if message.event in {
                Event.CONNECTION_STARTED,
                Event.CONNECTION_FAILED,
                Event.CONNECTION_FINISHED,
            }:
                message.connect_id = _read_string(stream)

        raw_size = stream.read(4)
        if len(raw_size) == 4:
            message.payload = stream.read(struct.unpack(">I", raw_size)[0])
        return message


def _read_string(stream: io.BytesIO) -> str:
    raw = stream.read(4)
    if len(raw) != 4:
        return ""
    size = struct.unpack(">I", raw)[0]
    return stream.read(size).decode("utf-8") if size else ""


def event_message(event: Event, payload: bytes = b"{}", session_id: str = "") -> bytes:
    return Message(
        msg_type=MsgType.FULL_CLIENT_REQUEST,
        flag=Flag.WITH_EVENT,
        event=event,
        session_id=session_id,
        payload=payload,
    ).encode()
