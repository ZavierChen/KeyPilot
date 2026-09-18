import json

from voice_assistant.providers.volcengine_protocol import Event, Flag, Message, MsgType, event_message


def test_start_connection_round_trip():
    data = event_message(Event.START_CONNECTION)
    decoded = Message.decode(data)
    assert decoded.msg_type == MsgType.FULL_CLIENT_REQUEST
    assert decoded.flag == Flag.WITH_EVENT
    assert decoded.event == Event.START_CONNECTION
    assert decoded.payload == b"{}"


def test_task_request_round_trip_with_session():
    payload = json.dumps({"req_params": {"text": "你好"}}, ensure_ascii=False).encode()
    data = event_message(Event.TASK_REQUEST, payload, "session-1")
    decoded = Message.decode(data)
    assert decoded.event == Event.TASK_REQUEST
    assert decoded.session_id == "session-1"
    assert decoded.payload == payload
