import json
from collections.abc import Generator, Iterable, Iterator
from typing import Any
from urllib.parse import urlparse

import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage


class SanvistDifyGuideTool(Tool):
    def _invoke(
        self,
        tool_parameters: dict[str, Any],
    ) -> Generator[ToolInvokeMessage, None, None]:
        query = str(tool_parameters.get("query") or "").strip()
        if not query:
            raise ValueError("作业指导问题不能为空")

        answer_parts: list[str] = []
        response_parts: list[str] = []
        target_conversation_id = str(
            tool_parameters.get("conversation_id") or ""
        ).strip()

        try:
            for item in self._call_guide(query, tool_parameters):
                kind = str(item.get("kind") or "")
                conversation_id = str(item.get("conversation_id") or "").strip()
                if conversation_id:
                    target_conversation_id = conversation_id

                if kind == "answer":
                    content = str(item.get("content") or "")
                    if not content:
                        continue
                    answer_parts.append(content)
                    response_parts.append(content)
                    yield self.create_stream_variable_message(
                        "response_stream", content
                    )
                    yield self.create_stream_variable_message(
                        "answer_stream", content
                    )
                elif kind == "progress":
                    progress = item.get("progress")
                    if not isinstance(progress, dict):
                        continue
                    frame = self._frame_progress(progress)
                    response_parts.append(frame)
                    yield self.create_stream_variable_message(
                        "response_stream", frame
                    )
                    yield self.create_stream_variable_message(
                        "progress_stream", frame
                    )
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            progress: dict[str, Any] = {
                "stage": "error",
                "phase": "failed",
                "message": message,
                "dify_event": "error",
            }
            if target_conversation_id:
                progress["conversation_id"] = target_conversation_id
            frame = self._frame_progress(progress)
            response_parts.append(frame)
            yield self.create_stream_variable_message("response_stream", frame)
            yield self.create_stream_variable_message("progress_stream", frame)
            fallback = f"Dify 作业指导调用失败：{message}"
            answer_parts.append(fallback)
            response_parts.append(fallback)
            yield self.create_stream_variable_message("response_stream", fallback)
            yield self.create_stream_variable_message("answer_stream", fallback)

        answer = "".join(answer_parts).strip()
        if not answer:
            raise RuntimeError("目标作业指导应用没有返回有效回答")

        yield self.create_variable_message(
            "response_output", "".join(response_parts)
        )
        yield self.create_variable_message("answer", answer)
        yield self.create_variable_message(
            "target_conversation_id", target_conversation_id
        )
        yield self.create_text_message(answer)

    def _call_guide(
        self,
        query: str,
        parameters: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        user_id = str(parameters.get("user_id") or "anonymous").strip()[:64]
        conversation_id = str(parameters.get("conversation_id") or "").strip()
        device_model = str(
            parameters.get("device_model") or "SCC4000A-8"
        ).strip()
        payload = {
            "inputs": {"device_model": device_model},
            "query": query,
            "response_mode": "streaming",
            "conversation_id": conversation_id,
            "user": user_id,
            "files": [],
        }

        final_conversation_id = conversation_id
        emitted_answer = False
        final_candidate = ""
        for event_name, data in self._stream_sse(payload):
            effective_event = str(
                data.get("event") or event_name or "message"
            ).lower()
            returned_id = str(data.get("conversation_id") or "").strip()
            if returned_id:
                final_conversation_id = returned_id

            if effective_event in {"message", "agent_message", "text_chunk"}:
                content = self._message_text(data)
                if content:
                    emitted_answer = True
                    yield {
                        "kind": "answer",
                        "content": content,
                        "conversation_id": final_conversation_id,
                    }
                continue

            if effective_event in {"error", "workflow_failed"}:
                message = self._first_text(
                    data, ("message", "error", "detail", "answer")
                ) or "作业指导 Dify 应用返回错误"
                raise RuntimeError(message)

            if effective_event == "workflow_finished":
                nested = data.get("data")
                detail = nested if isinstance(nested, dict) else data
                status = str(detail.get("status") or "").lower()
                if status not in {"", "succeeded"}:
                    message = self._first_text(
                        detail, ("error", "message", "status")
                    ) or "作业指导 Dify 工作流执行失败"
                    raise RuntimeError(message)
                final_candidate = self._extract_answer(detail.get("outputs"))

            if effective_event in {
                "workflow_started",
                "workflow_finished",
                "node_started",
                "node_finished",
                "agent_thought",
            }:
                progress = self._progress_data(effective_event, data)
                if final_conversation_id:
                    progress["conversation_id"] = final_conversation_id
                yield {
                    "kind": "progress",
                    "progress": progress,
                    "conversation_id": final_conversation_id,
                }

        if not emitted_answer and final_candidate:
            yield {
                "kind": "answer",
                "content": final_candidate,
                "conversation_id": final_conversation_id,
            }
            emitted_answer = True
        if not emitted_answer:
            raise RuntimeError("作业指导 Dify 应用没有返回 message/answer")

    def _stream_sse(
        self,
        payload: dict[str, Any],
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        with httpx.Client(
            timeout=httpx.Timeout(connect=10, read=180, write=10, pool=10),
            follow_redirects=True,
        ) as client:
            with client.stream(
                "POST",
                self._dify_url(),
                headers=self._dify_headers(),
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise RuntimeError(self._http_error(response))
                yield from self._iter_sse_events(response.iter_lines())

    def _dify_url(self) -> str:
        base_url = str(
            self.runtime.credentials.get("dify_base_url") or ""
        ).strip()
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Dify Service API 地址配置无效")
        base_url = base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return f"{base_url}/chat-messages"
        return f"{base_url}/v1/chat-messages"

    def _dify_headers(self) -> dict[str, str]:
        token = str(
            self.runtime.credentials.get("dify_api_key") or ""
        ).strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise ValueError("目标 Dify 应用 API Key 尚未配置")
        return {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    @staticmethod
    def _progress_data(
        event_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        nested = payload.get("data")
        detail = nested if isinstance(nested, dict) else payload
        title = str(detail.get("title") or "").strip()
        succeeded = str(detail.get("status") or "succeeded").lower() not in {
            "failed",
            "error",
            "stopped",
        }
        if event_name == "node_started":
            phase = "started"
            message = f"{title}正在执行" if title else "作业指导节点正在执行"
        elif event_name == "node_finished":
            if succeeded:
                phase = "completed"
                message = f"{title}执行完成" if title else "作业指导节点执行完成"
            else:
                phase = "failed"
                message = f"{title}执行失败" if title else "作业指导节点执行失败"
        else:
            phase = "started" if event_name.endswith("started") else "completed"
            message = {
                "workflow_started": "作业指导工作流已开始",
                "workflow_finished": "作业指导工作流已完成",
                "agent_thought": "作业指导助手正在分析",
            }.get(event_name, "作业指导工作流正在处理")
        return {
            "stage": event_name,
            "phase": phase,
            "message": message,
            "dify_event": event_name,
        }

    @staticmethod
    def _frame_progress(progress: dict[str, Any]) -> str:
        body = json.dumps(
            progress,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"<SANVIST>{body}</SANVIST>\n"

    @classmethod
    def _message_text(cls, payload: dict[str, Any]) -> str:
        direct = cls._first_text(payload, ("answer", "content", "text"))
        if direct:
            return direct
        nested = payload.get("data")
        if isinstance(nested, dict):
            return cls._first_text(nested, ("text", "answer", "content"))
        return ""

    @classmethod
    def _extract_answer(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("answer", "result", "output", "text", "content"):
                answer = cls._extract_answer(value.get(key))
                if answer:
                    return answer
            return ""
        if isinstance(value, list):
            return "\n".join(
                item for item in (cls._extract_answer(v) for v in value) if item
            )
        return str(value)

    @staticmethod
    def _first_text(payload: Any, keys: tuple[str, ...]) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in keys:
            value = payload.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, str):
                return value
            return json.dumps(value, ensure_ascii=False)
        return ""

    @staticmethod
    def _iter_sse_events(
        lines: Iterable[str],
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        event_name = ""
        data_lines: list[str] = []

        def flush() -> tuple[str, dict[str, Any]] | None:
            nonlocal event_name, data_lines
            raw_data = "\n".join(data_lines).strip()
            current_event = event_name
            event_name = ""
            data_lines = []
            if not raw_data or raw_data == "[DONE]":
                return None
            try:
                decoded = json.loads(raw_data)
            except json.JSONDecodeError:
                decoded = {"content": raw_data}
            if not isinstance(decoded, dict):
                decoded = {"content": decoded}
            return current_event, decoded

        for raw_line in lines:
            line = str(raw_line or "").rstrip("\r\n")
            if line == "":
                item = flush()
                if item is not None:
                    yield item
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        item = flush()
        if item is not None:
            yield item

    @staticmethod
    def _http_error(response: httpx.Response) -> str:
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                value = (
                    payload.get("detail")
                    or payload.get("message")
                    or payload.get("error")
                    or payload
                )
                detail = value if isinstance(value, str) else json.dumps(
                    value, ensure_ascii=False
                )
        except ValueError:
            detail = response.text.strip()
        suffix = f"：{detail}" if detail else ""
        return f"HTTP {response.status_code}{suffix}"
