from typing import Any
from urllib.parse import urlparse

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class SanvistDifyStreamProvider(ToolProvider):
    @staticmethod
    def _check(credentials: dict[str, Any]) -> None:
        base_url = str(credentials.get("dify_base_url") or "").strip()
        api_key = str(credentials.get("dify_api_key") or "").strip()
        if base_url or api_key:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ToolProviderCredentialValidationError(
                    "请填写以 http:// 或 https:// 开头的 Dify Service API 地址。"
                )
            if not api_key:
                raise ToolProviderCredentialValidationError(
                    "请同时填写目标 Dify 应用的 Service API Key。"
                )

    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        self._check(credentials)

    def validate_credentials(self, credentials: dict[str, Any]) -> None:
        self._check(credentials)
