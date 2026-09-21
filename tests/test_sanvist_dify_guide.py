import importlib.util
from pathlib import Path

import yaml
from dify_plugin.entities.tool import ToolInvokeMessage


MODULE_PATH = Path(__file__).parents[1] / "tools" / "sanvist_dify_guide.py"
SPEC = importlib.util.spec_from_file_location("sanvist_dify_guide", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
GuideTool = MODULE.SanvistDifyGuideTool


def test_operator_role_is_a_bindable_string_configuration():
    declaration_path = (
        Path(__file__).parents[1] / "tools" / "sanvist_dify_guide.yaml"
    )
    declaration = yaml.safe_load(declaration_path.read_text(encoding="utf-8"))
    parameter = next(
        item
        for item in declaration["parameters"]
        if item["name"] == "operator_role"
    )

    assert parameter["type"] == "string"
    assert parameter["form"] == "form"
    assert parameter["default"] == "novice_operator"
    assert "options" not in parameter


def test_payload_matches_dify_chat_messages_contract():
    tool = object.__new__(GuideTool)
    captured = {}

    def fake_stream(payload):
        captured.update(payload)
        return iter(
            [
                ("", {"event": "workflow_started"}),
                (
                    "",
                    {
                        "event": "workflow_finished",
                        "data": {
                            "status": "succeeded",
                            "outputs": {"answer": "作业步骤"},
                        },
                    },
                ),
            ]
        )

    tool._stream_sse = fake_stream
    items = list(
        tool._call_guide(
            "如何检查设备",
            {
                "user_id": "u-1",
                "device_model": "SCC4000A-8",
                "conversation_id": "conversation-1",
            },
        )
    )

    assert captured == {
        "inputs": {
            "device_model": "SCC4000A-8",
            "operator_role": "novice_operator",
        },
        "query": "如何检查设备",
        "response_mode": "streaming",
        "conversation_id": "conversation-1",
        "user": "u-1",
        "files": [],
    }
    assert [item["kind"] for item in items] == [
        "progress",
        "progress",
        "answer",
    ]
    assert items[-1]["content"] == "作业步骤"


def test_payload_forwards_operator_role_and_inspection_image():
    tool = object.__new__(GuideTool)
    captured = {}

    def fake_stream(payload):
        captured.update(payload)
        return iter(
            [("", {"event": "message", "answer": "检查结果"})]
        )

    tool._stream_sse = fake_stream
    list(
        tool._call_guide(
            "请检查照片",
            {
                "user_id": "u-2",
                "device_model": "390E-REEV",
                "operator_role": "skilled_operator",
                "inspection_image": {
                    "type": "image",
                    "transfer_method": "remote_url",
                    "remote_url": "https://files.example.com/check.jpg",
                    "mime_type": "image/jpeg",
                },
            },
        )
    )

    assert captured["inputs"] == {
        "device_model": "390E-REEV",
        "operator_role": "skilled_operator",
        "inspection_image": {
            "type": "image",
            "transfer_method": "remote_url",
            "url": "https://files.example.com/check.jpg",
        },
    }
    assert captured["files"] == []


def test_local_inspection_image_uses_absolute_preview_url():
    tool = object.__new__(GuideTool)
    tool.runtime = type(
        "Runtime",
        (),
        {"credentials": {"dify_base_url": "https://dify.example.com/v1"}},
    )()

    image = tool._inspection_image(
        {
            "type": "image",
            "transfer_method": "local_file",
            "url": "/files/file-id/file-preview?sign=test",
            "mime_type": "image/png",
        }
    )

    assert image == {
        "type": "image",
        "transfer_method": "remote_url",
        "url": "https://dify.example.com/files/file-id/file-preview?sign=test",
    }


def test_inspection_image_rejects_non_image_file():
    tool = object.__new__(GuideTool)
    try:
        tool._inspection_image(
            {
                "type": "document",
                "url": "https://files.example.com/manual.pdf",
                "mime_type": "application/pdf",
            }
        )
    except ValueError as exc:
        assert str(exc) == "现场照片必须是图片文件"
    else:
        raise AssertionError("non-image input should be rejected")


def test_guide_progress_is_flat_sanvist_json():
    progress = GuideTool._progress_data(
        "node_started",
        {"data": {"title": "检索作业知识"}},
    )
    frame = GuideTool._frame_progress(progress)
    assert progress == {
        "stage": "node_started",
        "phase": "started",
        "message": "检索作业知识正在执行",
        "dify_event": "node_started",
    }
    assert frame.startswith('<SANVIST>{"stage":"node_started"')
    assert '"event":"status"' not in frame
    assert '"data":' not in frame


def test_text_chunk_is_forwarded_without_python_event_envelope():
    tool = object.__new__(GuideTool)
    tool._stream_sse = lambda payload: iter(
        [
            ("", {"event": "text_chunk", "data": {"text": "第一步"}}),
        ]
    )
    items = list(tool._call_guide("问题", {"user_id": "u-1"}))
    assert items == [
        {"kind": "answer", "content": "第一步", "conversation_id": ""}
    ]


def test_guide_key_tolerates_bearer_prefix():
    tool = object.__new__(GuideTool)
    tool.runtime = type(
        "Runtime",
        (),
        {"credentials": {"dify_api_key": "Bearer secret"}},
    )()
    assert tool._dify_headers()["Authorization"] == "Bearer secret"


def test_guide_base_url_appends_chat_messages():
    tool = object.__new__(GuideTool)
    tool.runtime = type(
        "Runtime",
        (),
        {"credentials": {"dify_base_url": "https://dify.example.com/v1"}},
    )()
    assert tool._dify_url() == "https://dify.example.com/v1/chat-messages"


def test_chunker_preserves_split_component_tags_and_exact_text():
    chunker = MODULE._GuideAnswerChunker()
    component = (
        '<COMPONENT>\n{"scene":"guide","type":"source",'
        '"data":{"evidence":[]}}\n</COMPONENT>'
    )
    original = "普通正文" * 30 + component + "后续说明" * 25
    pieces = []
    for offset in range(0, len(original), 17):
        pieces.extend(chunker.feed(original[offset : offset + 17]))
    pieces.extend(chunker.finish())

    assert "".join(pieces) == original
    assert component in pieces
    assert all(len(piece) <= chunker.MAX_CHARS or piece == component for piece in pieces)


def test_large_guide_answer_reaches_stream_before_tool_finishes(monkeypatch):
    tool = object.__new__(GuideTool)
    tool.response_type = ToolInvokeMessage
    component = (
        '<COMPONENT>\n{"scene":"guide","type":"image",'
        '"data":{"items":[]}}\n</COMPONENT>'
    )
    answer = "先核对设备状态。" * 45 + component + "随后继续操作。" * 35
    upstream_finished = []
    delays = []

    def fake_call(query, parameters):
        yield {"kind": "answer", "content": answer}
        upstream_finished.append(True)

    tool._call_guide = fake_call
    monkeypatch.setattr(MODULE.time, "sleep", delays.append)

    output = tool._invoke({"query": "怎样操作"})
    first = next(output)
    assert first.message.variable_name == "response_stream"
    assert first.message.stream is True
    assert len(first.message.variable_value) <= MODULE._GuideAnswerChunker.MAX_CHARS
    assert not upstream_finished

    messages = [first, *output]
    streamed = {
        name: [
            item.message.variable_value
            for item in messages
            if item.type.value == "variable"
            and item.message.variable_name == name
            and item.message.stream
        ]
        for name in ("response_stream", "answer_stream")
    }
    assert upstream_finished
    assert "".join(streamed["response_stream"]) == answer
    assert "".join(streamed["answer_stream"]) == answer
    assert component in streamed["response_stream"]
    assert len(streamed["response_stream"]) > 10
    assert delays and all(delay == 0.025 for delay in delays)

    final_variables = {
        item.message.variable_name: item.message.variable_value
        for item in messages
        if item.type.value == "variable" and not item.message.stream
    }
    assert final_variables["answer"] == answer
    assert final_variables["response_output"] == answer


def test_native_small_upstream_chunks_are_not_artificially_delayed(monkeypatch):
    tool = object.__new__(GuideTool)
    tool.response_type = ToolInvokeMessage
    tool._call_guide = lambda query, parameters: iter(
        [
            {"kind": "answer", "content": "你好"},
            {"kind": "answer", "content": "，世界。"},
        ]
    )
    delays = []
    monkeypatch.setattr(MODULE.time, "sleep", delays.append)

    messages = list(tool._invoke({"query": "问候"}))
    parts = [
        item.message.variable_value
        for item in messages
        if item.type.value == "variable"
        and item.message.variable_name == "response_stream"
        and item.message.stream
    ]
    assert parts == ["你好", "，世界。"]
    assert delays == []
