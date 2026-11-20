"""
The workflows modules token on a connector's module routes (src/workflows_cdk/core/module_authentication.py).

A small connector is built in a temporary directory (one module with execute, content and schema routes, and a route
the connector adds on its Flask app) and served by the real Router. Auth0's key set is replaced by a key generated
here, so the tokens are real RS256 JWTs verified by authlib.
"""
import json
import logging
import sys
import textwrap
import time
import types

import pytest
from authlib.jose import JsonWebKey, jwt
from flask import Flask

from workflows_cdk.core import module_authentication
from workflows_cdk.core.module_authentication import ModuleAuthenticator

AUTH0_DOMAIN = "auth.stacksync.com"
AUTH0_AUDIENCE = "https://workflows-modules-prod/api"
SIGNING_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "signing-key"})
OTHER_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "other-key"})
MODULE_ROUTES = [("POST", "/greet/v1/execute"), ("POST", "/greet/v1/content"), ("GET", "/greet/v1/schema"), ("POST", "/greet/v1/schema")]
CORE_ROUTES = ["/", "/health", "/app-config", "/modules-list", "/routes"]

ROUTE_FILE = """
from flask import jsonify
from main import router


@router.route("/execute", methods=["POST"])
def execute():
    return {"ran": "execute"}


@router.route("/content", methods=["POST"])
def content():
    return {"ran": "content"}


@router.route("/schema", methods=["GET", "POST"])
def schema():
    return {"ran": "schema"}
"""


def mint_token(key=SIGNING_KEY, audience=AUTH0_AUDIENCE, issuer=f"https://{AUTH0_DOMAIN}/", expires_in=3600, algorithm="RS256"):
    now = int(time.time())
    header = {"alg": algorithm, "kid": key.as_dict()["kid"]} if algorithm == "RS256" else {"alg": algorithm}
    signing_key = key if algorithm == "RS256" else "a-shared-secret"
    return jwt.encode(header, {"iss": issuer, "aud": audience, "exp": now + expires_in, "iat": now, "sub": "client@clients"}, signing_key).decode()


@pytest.fixture
def connector_directory(tmp_path, monkeypatch):
    (tmp_path / "app_config.yaml").write_text('app_settings:\n  app_type: "greeter"\n  routes_directory: "src/modules"\n')
    module_directory = tmp_path / "src" / "modules" / "greet" / "v1"
    module_directory.mkdir(parents=True)
    (module_directory / "route.py").write_text(textwrap.dedent(ROUTE_FILE))
    (module_directory / "schema.json").write_text(json.dumps({"fields": []}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("ENVIRONMENT", "REGION", "WORKFLOWS_MODULES_AUTH_MODE", "WORKFLOWS_MODULES_AUTH0_DOMAIN", "WORKFLOWS_MODULES_AUTH0_AUDIENCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("REGION", "besg")
    key_set_fetches = []

    def fetch_key_set_document(self):
        key_set_fetches.append(self.auth0_domain)
        return {"keys": [SIGNING_KEY.as_dict(is_private=False)]}

    monkeypatch.setattr(ModuleAuthenticator, "fetch_key_set_document", fetch_key_set_document)
    return types.SimpleNamespace(path=tmp_path, key_set_fetches=key_set_fetches)


def build_connector():
    from workflows_cdk import Router

    app = Flask("greeter")
    router = Router(app)
    sys.modules.pop("main", None)

    @app.route("/webhook", methods=["POST"])
    def webhook():
        return {"ran": "webhook"}

    return app.test_client(), router


def call(client, method, path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.open(path, method=method, json={"data": {}}, headers=headers)


@pytest.mark.parametrize("mode", [None, "off"])
def test_off_runs_every_route_without_a_token_as_before(connector_directory, monkeypatch, mode):
    if mode:
        monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", mode)
    client, router = build_connector()

    assert router.app.before_request_funcs.get(None) in (None, [])
    for method, path in MODULE_ROUTES:
        assert call(client, method, path).status_code == 200, path
    assert connector_directory.key_set_fetches == []


def test_log_runs_a_call_without_a_valid_token_and_logs_it(connector_directory, monkeypatch, caplog):
    monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", "log")
    client, _ = build_connector()

    with caplog.at_level(logging.WARNING, logger=module_authentication.__name__):
        responses = [call(client, "POST", "/greet/v1/execute"), call(client, "POST", "/greet/v1/execute", token="not-a-jwt")]

    assert [response.status_code for response in responses] == [200, 200]
    assert [response.get_json()["data"] for response in responses] == [{"ran": "execute"}] * 2
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2 and all("(log): POST /greet/v1/execute" in message for message in messages)
    assert "no bearer token" in messages[0] and "invalid token" in messages[1]
    assert not any("not-a-jwt" in message for message in messages)


def test_log_does_not_log_a_valid_token(connector_directory, monkeypatch, caplog):
    monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", "log")
    client, _ = build_connector()

    with caplog.at_level(logging.WARNING, logger=module_authentication.__name__):
        assert call(client, "POST", "/greet/v1/execute", token=mint_token()).status_code == 200

    assert caplog.records == []


@pytest.mark.parametrize("method, path", MODULE_ROUTES)
def test_enforce_refuses_a_module_route_without_a_valid_token(connector_directory, monkeypatch, method, path):
    monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", "enforce")
    client, _ = build_connector()

    refused = [
        call(client, method, path),
        call(client, method, path, token="not-a-jwt"),
        call(client, method, path, token=mint_token(key=OTHER_KEY)),
        call(client, method, path, token=mint_token(audience="https://workflows-modules-dev/api")),
        call(client, method, path, token=mint_token(issuer="https://auth.dev.stacksync.com/")),
        call(client, method, path, token=mint_token(expires_in=-3600)),
        call(client, method, path, token=mint_token(algorithm="HS256")),
    ]

    assert [response.status_code for response in refused] == [401] * len(refused)
    assert refused[0].get_json() == {"error": "Unauthorized", "message": "A valid Stacksync token is required"}
    assert refused[0].headers["WWW-Authenticate"] == "Bearer"
    assert call(client, method, path, token=mint_token()).status_code == 200


def test_enforce_leaves_the_core_routes_and_the_connectors_own_routes_open(connector_directory, monkeypatch):
    monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", "enforce")
    client, _ = build_connector()

    # not refused: /routes answers 500 on any connector whose routes were discovered (a PosixPath in its JSON)
    for path in CORE_ROUTES:
        assert client.get(path).status_code not in (401, 503), path
    assert call(client, "POST", "/webhook").status_code == 200
    assert client.options("/greet/v1/execute").status_code == 200
    assert client.get("/no/such/route").status_code == 404


def test_enforce_answers_503_when_auth0_cannot_be_reached(connector_directory, monkeypatch):
    monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", "enforce")

    def unreachable(self):
        raise OSError("connection refused")

    monkeypatch.setattr(ModuleAuthenticator, "fetch_key_set_document", unreachable)
    client, _ = build_connector()

    assert call(client, "POST", "/greet/v1/execute", token=mint_token()).status_code == 503


def test_the_key_set_is_fetched_once_and_an_unknown_key_refetches_it_at_most_once_a_minute(connector_directory, monkeypatch):
    monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", "enforce")
    client, _ = build_connector()

    for _ in range(3):
        assert call(client, "POST", "/greet/v1/execute", token=mint_token()).status_code == 200
    for _ in range(3):
        assert call(client, "POST", "/greet/v1/execute", token=mint_token(key=OTHER_KEY)).status_code == 401

    assert connector_directory.key_set_fetches == [AUTH0_DOMAIN]


def test_the_mode_comes_from_the_mounted_regional_variables_and_the_environment_wins(connector_directory, monkeypatch):
    regional_directory = connector_directory.path / "environment_variables" / "regional"
    regional_directory.mkdir(parents=True)
    (regional_directory / "variables_prod_besg.env").write_text("SOME_OTHER_VARIABLE=1\nWORKFLOWS_MODULES_AUTH_MODE=enforce\n")

    assert ModuleAuthenticator().mode == "enforce"
    monkeypatch.setenv("WORKFLOWS_MODULES_AUTH_MODE", "log")
    assert ModuleAuthenticator().mode == "log"
    monkeypatch.setenv("REGION", "usnv")
    monkeypatch.delenv("WORKFLOWS_MODULES_AUTH_MODE")
    assert ModuleAuthenticator().mode == "off"


def test_a_private_app_without_any_setting_is_off(connector_directory, monkeypatch):
    # a customer's app deployed by the cdk-deployment-service: no ENVIRONMENT, no REGION, no mounted file
    monkeypatch.delenv("ENVIRONMENT")
    monkeypatch.delenv("REGION")

    assert ModuleAuthenticator().mode == "off"


def test_an_unknown_mode_logs_instead_of_turning_the_check_off_or_refusing_calls(connector_directory):
    assert ModuleAuthenticator({"WORKFLOWS_MODULES_AUTH_MODE": "enforced"}).mode == "log"


@pytest.mark.parametrize(
    "environment, domain, audience",
    [
        ("prod", "auth.stacksync.com", "https://workflows-modules-prod/api"),
        ("stage", "auth.stage.stacksync.com", "https://workflows-modules-stage/api"),
        ("dev", "auth.dev.stacksync.com", "https://workflows-modules-dev/api"),
    ],
)
def test_each_environment_verifies_its_own_modules_api(connector_directory, monkeypatch, environment, domain, audience):
    monkeypatch.setenv("ENVIRONMENT", environment)
    authenticator = ModuleAuthenticator({})

    assert (authenticator.auth0_domain, authenticator.auth0_audience) == (domain, audience)
