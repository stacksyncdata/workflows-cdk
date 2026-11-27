"""What the Router sends to Sentry.

A ManagedError is raised on purpose to show the user a message (missing connection, invalid
input, upstream quota): it must never reach Sentry. Any other exception is a bug and must reach
Sentry exactly once, even though the Router turns it into a ManagedError for the response.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
import sentry_sdk
from flask import Flask
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.transport import Transport

from workflows_cdk import ManagedError, Request, Router
from workflows_cdk.core import dynamic_routing, sentry
from workflows_cdk.core.dynamic_routing import wrap_route_handler


class InMemoryTransport(Transport):
    """Keeps the events the real SDK would send, so a duplicate from any integration is counted."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:
        self.events += [item.payload.json for item in envelope.items if item.type == "event"]

    def capture_event(self, event: dict) -> None:  # sentry-sdk 1.x sends events here
        self.events.append(event)


@pytest.fixture
def sentry_transport() -> Iterator[InMemoryTransport]:
    """The real SDK with its default integrations (logging included), sending to memory."""
    sentry_transport = InMemoryTransport()
    sentry_sdk.init(
        dsn="https://public@example.ingest.sentry.io/1",
        integrations=[FlaskIntegration()],
        transport=sentry_transport,
    )
    yield sentry_transport
    sentry_sdk.init()


def sent_exception_types(sentry_transport: InMemoryTransport) -> list[str]:
    sentry_sdk.flush()
    return [event["exception"]["values"][-1]["type"] for event in sentry_transport.events]


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


def test_managed_error_is_not_sent_to_sentry(app: Flask, sentry_transport: InMemoryTransport) -> None:
    response = app.test_client().post("/raise_managed_error", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing PostgreSQL connection. Please configure a connection."
    assert sent_exception_types(sentry_transport) == []


def test_unexpected_error_is_sent_to_sentry_once(app: Flask, sentry_transport: InMemoryTransport) -> None:
    response = app.test_client().post("/raise_bug", json={})

    assert response.get_json()["error"].startswith("Internal server error")
    assert sent_exception_types(sentry_transport) == ["TypeError"]


@pytest.mark.parametrize(
    "request_body",
    [{"credentials": None}, {"credentials": {"connection_data": None}}, [1, 2]],
)
def test_credentials_of_a_null_or_odd_body_are_empty(
    app: Flask, sentry_transport: InMemoryTransport, request_body: object
) -> None:
    response = app.test_client().post("/read_credentials", json=request_body)

    assert response.status_code == 200
    assert response.get_json()["data"] == {"credentials": {}}
    assert sent_exception_types(sentry_transport) == []


def test_sentry_is_not_initialized_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    initialized_options: list[dict] = []
    monkeypatch.setattr(sentry.sentry_sdk, "init", lambda **options: initialized_options.append(options))
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    sentry.init_sentry(Flask(__name__), "https://public@example.ingest.sentry.io/1")
    assert initialized_options == []

    monkeypatch.setenv("ENVIRONMENT", "prod")
    sentry.init_sentry(Flask(__name__), "https://public@example.ingest.sentry.io/1")
    assert [options["environment"] for options in initialized_options] == ["prod"]
