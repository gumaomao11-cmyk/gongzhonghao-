"""Quick test: verify LLMClient error wrapping produces a useful hint."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.client import LLMClient, LLMError
from src.utils.config import load_config


def test_404_error_wrapping():
    """Simulate a 404 from volcengine and verify the hint is generated."""
    cfg = load_config("config.example.yaml")
    client = LLMClient.__new__(LLMClient)
    client.cfg = cfg

    fake = Exception(
        "Error code: 404 - {'error': {'code': 'InvalidEndpointOrModel.NotFound', "
        "'message': 'The model or endpoint deepseek-v3 does not exist'}}"
    )
    err = client._wrap_error(fake)
    assert err.code == "HTTP_404" or err.code == "InvalidEndpointOrModel.NotFound"
    assert err.hint
    assert "console.volcengine.com" in err.hint
    print(f"  [OK] code={err.code}")
    print(f"  [OK] hint: {err.hint[:120]}...")


def test_auth_error_wrapping():
    cfg = load_config("config.example.yaml")
    client = LLMClient.__new__(LLMClient)
    client.cfg = cfg

    fake = Exception("Error code: 401 - {'error': {'message': 'Authentication failed'}}")
    err = client._wrap_error(fake)
    assert "api_key" in err.hint.lower() or "expired" in err.hint.lower()
    print(f"  [OK] 401 hint: {err.hint}")


def test_rate_limit_wrapping():
    cfg = load_config("config.example.yaml")
    client = LLMClient.__new__(LLMClient)
    client.cfg = cfg

    fake = Exception("Error code: 429 - rate limit exceeded")
    err = client._wrap_error(fake)
    assert "rate" in err.hint.lower() or "rpm" in err.hint.lower()
    print(f"  [OK] 429 hint: {err.hint}")


def test_llm_error_message_format():
    err = LLMError("X", "msg", "hint here")
    s = str(err)
    assert "X" in s and "msg" in s and "hint" in s
    print(f"  [OK] LLMError.__str__: {s!r}")


if __name__ == "__main__":
    print("=== error wrapping tests ===")
    test_404_error_wrapping()
    test_auth_error_wrapping()
    test_rate_limit_wrapping()
    test_llm_error_message_format()
    print()
    print("=== all error-wrap tests passed ===")
