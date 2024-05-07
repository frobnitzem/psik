import pytest

from aiohttp.web import HTTPClientError
from psik.web import sign_message, verify_signature

def test_sign():
    ans = sign_message("Hello, World!", "It's a Secret to Everybody")
    assert ans == "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"

def test_verify():
    ans = sign_message("X", "Y")
    verify_signature("X", "Y", ans)
    with pytest.raises(HTTPClientError):
        verify_signature("X", "X", ans)
    with pytest.raises(HTTPClientError):
        verify_signature("Y", "Y", ans)
