"""The file-based schema routes must consume the request body before answering.

A module that ships only a schema.json gets its /schema route from the Router. That handler
never needed the body, so it never read it. Under gunicorn's sync worker the connection is then
closed with unread bytes still queued, the kernel answers with a TCP reset, and Cloud Run reports
a 502 for every POST larger than one 8 KB socket read (seen in prod on netsuite suiteql_query,
whose callers post a 12 KB credentials payload).

The test wraps the WSGI input stream and checks that the handler drained it completely.
"""

import io
import json
import os
from pathlib import Path

import pytest
from flask import Flask

from workflows_cdk import Router


SCHEMA = {"metadata": {"workflows_module_schema_version": "1.0.0"}, "fields": [{"id": "query"}]}
LARGE_BODY = json.dumps({"data": {"form_data": {}}, "credentials": {"value": "x" * 12000}}).encode()


class CountingInput(io.BytesIO):
    """A wsgi.input that records how many bytes the application actually read."""

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk

    def readline(self, size: int = -1) -> bytes:
        chunk = super().readline(size)
        self.bytes_read += len(chunk)
        return chunk


@pytest.fixture
def app_with_file_only_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flask:
    """A connector whose module ships only a schema.json, laid out like the fleet apps."""
    module_directory = tmp_path / "src" / "modules" / "static_only" / "v1"
    module_directory.mkdir(parents=True)
    (module_directory / "schema.json").write_text(json.dumps(SCHEMA))
    (tmp_path / "app_config.yaml").write_text(
        "app_settings:\n"
        "  app_type: verify\n"
        "  app_name: Verify\n"
        "  routes_directory: src/modules\n"
    )
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.chdir(tmp_path)
    app = Flask(__name__)
    Router(app)
    return app


def post_schema(app: Flask, path: str) -> tuple[int, dict, CountingInput]:
    wsgi_input = CountingInput(LARGE_BODY)
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = int(status.split()[0])

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(LARGE_BODY)),
        "wsgi.input": wsgi_input,
        "wsgi.url_scheme": "http",
        "wsgi.version": (1, 0),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": False,
    }
    body = b"".join(app.wsgi_app(environ, start_response))
    return captured["status"], json.loads(body), wsgi_input


def test_registered_schema_route_consumes_large_post_body(app_with_file_only_module: Flask) -> None:
    status, body, wsgi_input = post_schema(app_with_file_only_module, "/static_only/v1/schema")

    assert status == 200
    assert body["data"]["schema"] == SCHEMA
    assert wsgi_input.bytes_read == len(LARGE_BODY)


def test_catch_all_schema_route_consumes_large_post_body(app_with_file_only_module: Flask) -> None:
    # A module added after startup is served by the catch-all handler; it must drain the body too.
    late_module = Path(os.getcwd()) / "src" / "modules" / "added_later" / "v1"
    late_module.mkdir(parents=True)
    (late_module / "schema.json").write_text(json.dumps(SCHEMA))

    status, body, wsgi_input = post_schema(app_with_file_only_module, "/added_later/v1/schema")

    assert status == 200
    assert body["data"]["schema"] == SCHEMA
    assert wsgi_input.bytes_read == len(LARGE_BODY)
