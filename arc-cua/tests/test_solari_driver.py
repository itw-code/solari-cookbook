"""Contract tests for SolariCloudDriver against the live-verified Solari API (docs/SOLARI_API.md).

All tests are offline: HTTP goes through an injected fake requester.
"""

import io
import json
import logging
import urllib.error
import urllib.request

import pytest

from arc_cua.cloud.solari_driver import (
    SessionStatus,
    SessionType,
    SolariAPIError,
    SolariCloudDriver,
    SolariConfigError,
)

KEY = "slr_live_abcd1234_supersecretvalue"
# Shapes copied from the 2026-09-26 live probe; ids/endpoints are signed capabilities.
SIGNED_ID = "FAKEsignedSessionId_0000000000000000000000000000000000000000000000000000.fakeSignature0000"
CREATE_RESPONSE = {
    "sessionId": SIGNED_ID,
    "wsEndpoint": f"wss://api.getsolari.com/ws/{SIGNED_ID}",
    "cdpEndpoint": f"wss://api.getsolari.com/cdp/{SIGNED_ID}",
    "expiresAt": "2026-09-26T17:29:12.525Z",
}


def http_error(status: int, body: dict | str) -> urllib.error.HTTPError:
    raw = body if isinstance(body, str) else json.dumps(body)
    return urllib.error.HTTPError("https://api.getsolari.com/x", status, "err", {}, io.BytesIO(raw.encode()))


class FakeHTTP:
    """Records requests; replies with queued responses (dict/None) or raises queued exceptions."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        reply = self.responses.pop(0) if self.responses else None
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def body(self, i: int) -> dict:
        return json.loads(self.requests[i].data.decode())

    def header(self, i: int, name: str) -> str | None:
        # urllib normalises header names with str.capitalize()
        return self.requests[i].get_header(name.capitalize())


@pytest.fixture(autouse=True)
def no_ambient_key(monkeypatch):
    for var in ("SOLARI_API_KEY", "SOLARI_BASE_URL", "SOLARI_API_URL"):
        monkeypatch.delenv(var, raising=False)


def make_driver(http: FakeHTTP, **kw) -> SolariCloudDriver:
    return SolariCloudDriver(api_key=KEY, http_requester=http, sleep=lambda s: None, register_atexit=False, **kw)


# --- configuration ---------------------------------------------------------------------------

def test_missing_key_raises_instead_of_silent_mock():
    with pytest.raises(SolariConfigError, match="SOLARI_API_KEY"):
        SolariCloudDriver(register_atexit=False)


def test_key_read_from_env(monkeypatch):
    monkeypatch.setenv("SOLARI_API_KEY", KEY)
    assert SolariCloudDriver(register_atexit=False).is_mock is False


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("SOLARI_BASE_URL", "https://staging.example.com/")
    http = FakeHTTP(CREATE_RESPONSE)
    make_driver(http).provision_browser()
    assert http.requests[0].full_url == "https://staging.example.com/sessions"


def test_explicit_mock_needs_no_key_and_makes_no_http():
    http = FakeHTTP()
    driver = SolariCloudDriver(mock=True, http_requester=http, register_atexit=False)
    session = driver.provision_browser()
    assert driver.is_mock and session.is_mock
    assert session.cdp_endpoint
    driver.terminate(session.session_id)
    assert http.requests == []


# --- create ----------------------------------------------------------------------------------

def test_create_sends_only_documented_fields_with_auth_and_idempotency():
    http = FakeHTTP(CREATE_RESPONSE)
    make_driver(http).provision_browser(stealth=True, recording=True, profile_id="p1", proxy="us", captcha=True)

    req = http.requests[0]
    assert req.get_method() == "POST"
    assert req.full_url == "https://api.getsolari.com/sessions"
    assert http.header(0, "Authorization") == f"Bearer {KEY}"
    assert http.header(0, "Idempotency-Key")
    assert http.body(0) == {"stealth": True, "recording": True, "profileId": "p1", "proxy": "us", "captcha": True}


def test_create_default_body_is_empty():
    http = FakeHTTP(CREATE_RESPONSE)
    make_driver(http).provision_browser()
    assert http.body(0) == {}


def test_create_parses_live_response_shape():
    http = FakeHTTP(CREATE_RESPONSE)
    session = make_driver(http).provision_browser()
    assert session.session_id == SIGNED_ID
    assert session.cdp_endpoint == CREATE_RESPONSE["cdpEndpoint"]
    assert session.ws_endpoint == CREATE_RESPONSE["wsEndpoint"]
    assert session.expires_at == CREATE_RESPONSE["expiresAt"]
    assert session.session_type == SessionType.BROWSER
    assert session.status == SessionStatus.RUNNING
    assert session.is_mock is False


def test_create_accepts_id_field_as_well():
    body = {k: v for k, v in CREATE_RESPONSE.items() if k != "sessionId"} | {"id": "plain-id"}
    session = make_driver(FakeHTTP(body)).provision_browser()
    assert session.session_id == "plain-id"


def test_create_without_cdp_endpoint_raises_and_releases():
    body = {"sessionId": SIGNED_ID, "wsEndpoint": "wss://x/ws/y"}
    http = FakeHTTP(body, None)
    driver = make_driver(http)
    with pytest.raises(SolariAPIError, match="cdpEndpoint"):
        driver.provision_browser()
    assert http.requests[1].get_method() == "DELETE"
    assert driver.list_active_sessions() == []


def test_create_http_error_raises_structured_error_no_fallback():
    http = FakeHTTP(http_error(429, {"error": "too many", "code": "ConcurrencyLimitExceeded"}))
    with pytest.raises(SolariAPIError) as exc:
        make_driver(http).provision_browser()
    assert exc.value.status == 429
    assert exc.value.code == "ConcurrencyLimitExceeded"
    assert exc.value.retryable is False
    assert len(http.requests) == 1  # 429 is not retried


def test_transient_5xx_retried_with_same_idempotency_key():
    http = FakeHTTP(http_error(503, {"error": "busy", "code": "NoCapacity"}), CREATE_RESPONSE)
    session = make_driver(http).provision_browser()
    assert session.session_id == SIGNED_ID
    assert len(http.requests) == 2
    assert http.header(0, "Idempotency-Key") == http.header(1, "Idempotency-Key")


def test_transient_5xx_gives_up_after_max_retries():
    errors = [http_error(502, "bad gateway") for _ in range(3)]
    http = FakeHTTP(*errors)
    with pytest.raises(SolariAPIError) as exc:
        make_driver(http, max_retries=2).provision_browser()
    assert exc.value.status == 502 and exc.value.retryable is True
    assert len(http.requests) == 3


def test_non_json_error_body_still_raises_cleanly():
    http = FakeHTTP(http_error(404, "404 Not Found"))
    with pytest.raises(SolariAPIError) as exc:
        make_driver(http).provision_browser()
    assert exc.value.status == 404 and exc.value.code is None


# --- release ---------------------------------------------------------------------------------

def test_terminate_sends_delete_and_is_idempotent():
    http = FakeHTTP(CREATE_RESPONSE, None)
    driver = make_driver(http)
    session = driver.provision_browser()

    assert driver.terminate(session.session_id) is True
    assert http.requests[1].get_method() == "DELETE"
    assert http.requests[1].full_url.endswith(f"/sessions/{SIGNED_ID}")
    assert session.status == SessionStatus.TERMINATED
    assert driver.terminate(session.session_id) is True
    assert len(http.requests) == 2


def test_terminate_404_counts_as_released():
    http = FakeHTTP(CREATE_RESPONSE, http_error(404, "404 Not Found"))
    driver = make_driver(http)
    session = driver.provision_browser()
    assert driver.terminate(session.session_id) is True
    assert session.status == SessionStatus.TERMINATED


def test_terminate_failure_keeps_session_active_for_retry():
    http = FakeHTTP(CREATE_RESPONSE, http_error(500, "boom"), None)
    driver = make_driver(http, max_retries=0)
    session = driver.provision_browser()
    assert driver.terminate(session.session_id) is False
    assert session.is_active()
    assert driver.terminate(session.session_id) is True


def test_context_manager_releases_all_sessions():
    http = FakeHTTP(CREATE_RESPONSE, None)
    with make_driver(http) as driver:
        driver.provision_browser()
    assert [r.get_method() for r in http.requests] == ["POST", "DELETE"]


def test_terminate_unknown_session_returns_false():
    assert make_driver(FakeHTTP()).terminate("nope") is False


# --- secrets ---------------------------------------------------------------------------------

def test_repr_and_logs_never_contain_key_id_or_endpoints(caplog):
    caplog.set_level(logging.DEBUG, logger="arc_cua.cloud.solari_driver")
    http = FakeHTTP(CREATE_RESPONSE, None)
    driver = make_driver(http)
    session = driver.provision_browser()
    driver.terminate(session.session_id)

    for text in (repr(session), repr(driver), caplog.text):
        assert KEY not in text
        assert SIGNED_ID not in text
        assert CREATE_RESPONSE["cdpEndpoint"] not in text


def test_error_message_does_not_leak_key():
    http = FakeHTTP(http_error(403, {"error": f"bad key {KEY}", "code": "Forbidden"}))
    with pytest.raises(SolariAPIError) as exc:
        make_driver(http).provision_browser()
    assert KEY not in str(exc.value)


# --- desktop ---------------------------------------------------------------------------------

def test_live_desktop_is_explicitly_unsupported():
    http = FakeHTTP()
    with pytest.raises(NotImplementedError, match="accessibility"):
        make_driver(http).provision_desktop()
    assert http.requests == []


def test_mock_desktop_still_available_for_offline_benchmarks():
    driver = SolariCloudDriver(mock=True, register_atexit=False)
    session = driver.provision_desktop()
    assert session.is_mock and session.session_type == SessionType.DESKTOP
