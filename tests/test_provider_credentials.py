import importlib.util
from pathlib import Path

import pytest
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


MODULE_PATH = (
    Path(__file__).parents[1] / "provider" / "sanvist_dify_stream.py"
)
SPEC = importlib.util.spec_from_file_location(
    "sanvist_dify_stream_provider", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Provider = MODULE.SanvistDifyStreamProvider


def test_empty_credentials_are_allowed_until_a_tool_is_used():
    Provider._check({})


def test_one_dify_credential_pair_is_valid():
    Provider._check(
        {
            "dify_base_url": "https://dify.example.com",
            "dify_api_key": "app-operations",
        }
    )


@pytest.mark.parametrize(
    "credentials",
    [
        {"dify_base_url": "https://dify.example.com"},
        {"dify_api_key": "app-operations"},
    ],
)
def test_partially_configured_credentials_are_rejected(credentials):
    with pytest.raises(ToolProviderCredentialValidationError):
        Provider._check(credentials)
