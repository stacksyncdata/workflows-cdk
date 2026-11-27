"""What the Router sends to Sentry.

A ManagedError is raised on purpose to show the user a message (missing connection, invalid
input, upstream quota): it must never reach Sentry. Any other exception is a bug and must reach
Sentry exactly once, even though the Router turns it into a ManagedError for the response.
"""

from pathlib import Path

import pytest
from flask import Flask

from workflows_cdk import ManagedError, Request, Router
from workflows_cdk.core import dynamic_routing, sentry
from workflows_cdk.core.dynamic_routing import wrap_route_handler


@pytest.fixture
def captured_exceptions(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    captured_exceptions: list[BaseException] = []
    monkeypatch.setattr(dynamic_routing.sentry_sdk, "capture_exception", captured_exceptions.append)
    return captured_exceptions


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flask:
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.chdir(tmp_path)
    app = Flask(__name__)
    Router(app)

    def raise_managed_error():
        raise ManagedError("Missing PostgreSQL connection. Please configure a connection.")

    def raise_bug():
        raise TypeError("'NoneType' object is not iterable")

    def read_credentials():
        return {"credentials": Request(dynamic_routing.flask_request).credentials}

    for handler in (raise_managed_error, raise_bug, read_credentials):
        app.add_url_rule(f"/{handler.__name__}", view_func=wrap_route_handler(handler), methods=["POST"])
    return app


def test_managed_error_is_not_sent_to_sentry(app: Flask, captured_exceptions: list[BaseException]) -> None:
    response = app.test_client().post("/raise_managed_error", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing PostgreSQL connection. Please configure a connection."
    assert captured_exceptions == []


def test_unexpected_error_is_sent_to_sentry_once(app: Flask, captured_exceptions: list[BaseException]) -> None:
    response = app.test_client().post("/raise_bug", json={})

    assert response.get_json()["error"].startswith("Internal server error")
    assert [type(exception) for exception in captured_exceptions] == [TypeError]


@pytest.mark.parametrize(
    "request_body",
    [{"credentials": None}, {"credentials": {"connection_data": None}}, [1, 2]],
)
def test_credentials_of_a_null_or_odd_body_are_empty(
    app: Flask, captured_exceptions: list[BaseException], request_body: object
) -> None:
    response = app.test_client().post("/read_credentials", json=request_body)

    assert response.status_code == 200
    assert response.get_json()["data"] == {"credentials": {}}
    assert captured_exceptions == []


def test_sentry_is_not_initialized_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    initialized_options: list[dict] = []
    monkeypatch.setattr(sentry.sentry_sdk, "init", lambda **options: initialized_options.append(options))
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    sentry.init_sentry(Flask(__name__), "https://public@example.ingest.sentry.io/1")
    assert initialized_options == []

    monkeypatch.setenv("ENVIRONMENT", "prod")
    sentry.init_sentry(Flask(__name__), "https://public@example.ingest.sentry.io/1")
    assert [options["environment"] for options in initialized_options] == ["prod"]
