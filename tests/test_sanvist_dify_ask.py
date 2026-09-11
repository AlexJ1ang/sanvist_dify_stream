import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "sanvist_dify_ask.py"
SPEC = importlib.util.spec_from_file_location("sanvist_dify_ask", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ToolClass = MODULE.SanvistDifyAskTool


def test_progress_frame_is_flat_and_keeps_sanvist_wrapper():
    progress = {
        "stage": "node_started",
        "phase": "started",
        "message": "开始正在执行",
        "dify_event": "node_started",
        "conversation_id": "c-1",
    }
    assert ToolClass._frame_progress(progress) == (
        '<SANVIST>{"stage":"node_started","phase":"started",'
        '"message":"开始正在执行","dify_event":"node_started",'
        '"conversation_id":"c-1"}</SANVIST>\n'
    )


def test_node_title_becomes_progress_message_without_event_data_envelope():
    progress = ToolClass._progress_data(
        "node_finished",
        {"data": {"title": "查询事实数据", "status": "succeeded"}},
    )
    assert progress == {
        "stage": "node_finished",
        "phase": "completed",
        "message": "查询事实数据执行完成",
        "dify_event": "node_finished",
    }
    assert "event" not in progress
    assert "data" not in progress


def test_dify_stream_keeps_answer_chunks_and_native_progress():
    tool = object.__new__(ToolClass)
    tool._stream_sse = lambda payload: iter(
        [
            ("", {"event": "workflow_started", "conversation_id": "c-1"}),
            (
                "",
                {
                    "event": "node_started",
                    "conversation_id": "c-1",
                    "data": {"title": "指标加工与事实句"},
                },
            ),
            ("", {"event": "message", "answer": "报表", "conversation_id": "c-1"}),
            ("", {"event": "message", "answer": "正文", "conversation_id": "c-1"}),
            (
                "",
                {
                    "event": "node_finished",
                    "conversation_id": "c-1",
                    "data": {
                        "title": "指标加工与事实句",
                        "status": "succeeded",
                    },
                },
            ),
        ]
    )
    items = list(
        tool._call_dify(
            "生成报表",
            {
                "user_id": "u1",
                "role_id": "OWNER",
                "device_list": "[]",
                "language": "简体中文(zh-CN)",
            },
        )
    )
    assert [item["kind"] for item in items] == [
        "progress",
        "progress",
        "answer",
        "answer",
        "progress",
    ]
    assert items[1]["progress"]["message"] == "指标加工与事实句正在执行"
    assert items[2]["content"] == "报表"
    assert items[3]["content"] == "正文"


def test_bearer_prefix_is_removed_from_configured_key():
    tool = object.__new__(ToolClass)
    tool.runtime = type(
        "Runtime",
        (),
        {"credentials": {"dify_api_key": "Bearer app-test"}},
    )()
    assert tool._dify_headers()["Authorization"] == "Bearer app-test"


def test_data_only_sse_is_parsed():
    lines = [
        'data: {"event":"message","answer":"你好"}',
        "",
        "data: [DONE]",
        "",
    ]
    assert list(ToolClass._iter_sse_events(lines)) == [
        ("", {"event": "message", "answer": "你好"})
    ]


def test_role_and_input_mappings_match_target_app():
    assert ToolClass._map_role("OWNER") == "OWNER"
    assert ToolClass._map_role("ADMIN") == "ADMIN"
    assert ToolClass._map_role("MAINTAINER") == "MAINTAINER"
    assert ToolClass._map_role("PURCHASER") == "PURCHASER"
    assert ToolClass._map_role("OPERATOR") == "OPERATOR"
    assert ToolClass._map_role("boss") == "OWNER"
    assert ToolClass._map_role("dispatcher") == "ADMIN"
    assert ToolClass._device_list_json('[{"deviceId":"BC1"}]') == (
        '[{"deviceId":"BC1"}]'
    )


def test_channel_is_normalized_and_unknown_values_are_dropped():
    assert ToolClass._channel("APP") == "app"
    assert ToolClass._channel(" Vehicle ") == "vehicle"
    assert ToolClass._channel("pc") == "pc"
    assert ToolClass._channel("") == ""
    assert ToolClass._channel(None) == ""
    assert ToolClass._channel("web") == ""


def test_channel_is_forwarded_only_when_present():
    captured: dict[str, dict] = {}

    def fake_stream(payload):
        captured["payload"] = payload
        return iter(
            [("", {"event": "message", "answer": "好", "conversation_id": "c-1"})]
        )

    tool = object.__new__(ToolClass)
    tool._stream_sse = fake_stream
    list(
        tool._call_dify(
            "查询设备",
            {"user_id": "u1", "role_id": "OWNER", "channel": "APP"},
        )
    )
    assert captured["payload"]["inputs"]["channel"] == "app"

    captured.clear()
    list(tool._call_dify("查询设备", {"user_id": "u1", "role_id": "OWNER"}))
    assert "channel" not in captured["payload"]["inputs"]


def test_failed_workflow_finished_surfaces_the_real_error():
    tool = object.__new__(ToolClass)
    tool._stream_sse = lambda payload: iter(
        [
            ("", {"event": "workflow_started", "conversation_id": "c-1"}),
            (
                "",
                {
                    "event": "workflow_finished",
                    "conversation_id": "c-1",
                    "data": {
                        "status": "failed",
                        "error": "role_id value is invalid",
                    },
                },
            ),
        ]
    )

    try:
        list(tool._call_dify("查询设备", {"user_id": "u1", "role_id": "OWNER"}))
    except RuntimeError as exc:
        assert str(exc) == "role_id value is invalid"
    else:
        raise AssertionError("failed workflow_finished must raise RuntimeError")


def test_workflow_finished_outputs_are_used_as_answer_fallback():
    tool = object.__new__(ToolClass)
    tool._stream_sse = lambda payload: iter(
        [
            (
                "",
                {
                    "event": "workflow_finished",
                    "conversation_id": "c-1",
                    "data": {
                        "status": "succeeded",
                        "outputs": {"final": "最终回答"},
                    },
                },
            )
        ]
    )

    items = list(
        tool._call_dify("查询设备", {"user_id": "u1", "role_id": "OWNER"})
    )
    assert [item["kind"] for item in items] == ["answer", "progress"]
    assert items[0]["content"] == "最终回答"
