"""
Authentication of the calls to a connector's module routes.

Stacksync's services (the workflow engine, frontend-logics, genies) call a managed connector with the workflows
modules machine token, an Auth0 RS256 JWT, in `Authorization: Bearer <token>`. The mode says what a call without a
valid token gets:

- off: nothing is checked (the default, and what a customer's private app runs with);
- log: the call runs and is logged, to find callers that send no token before enforcing;
- enforce: the call is refused with 401.

The mode and the Auth0 settings are read from the environment, then from the regional variables file Stacksync
mounts on its managed connectors only (environment_variables/regional/variables_<environment>_<region>.env), so one
change of that file reaches every managed connector at its next start.
"""
import json
import logging
import os
import threading
import time
import urllib.request
from typing import Dict, Optional

from dotenv import dotenv_values
from flask import jsonify, request

from .get_environment import get_environment

logger = logging.getLogger(__name__)

MODE_SETTING_NAME = "WORKFLOWS_MODULES_AUTH_MODE"
AUTH0_DOMAIN_SETTING_NAME = "WORKFLOWS_MODULES_AUTH0_DOMAIN"
AUTH0_AUDIENCE_SETTING_NAME = "WORKFLOWS_MODULES_AUTH0_AUDIENCE"

OFF_MODE = "off"
LOG_MODE = "log"
ENFORCE_MODE = "enforce"
MODES = (OFF_MODE, LOG_MODE, ENFORCE_MODE)

# the workflows modules API of each environment, as workflows-module-http-requests verifies it
DEFAULT_AUTH0_SETTINGS_BY_ENVIRONMENT = {
    "prod": ("auth.stacksync.com", "https://workflows-modules-prod/api"),
    "stage": ("auth.stage.stacksync.com", "https://workflows-modules-stage/api"),
    "dev": ("auth.dev.stacksync.com", "https://workflows-modules-dev/api"),
}

JWKS_LIFETIME_SECONDS = 600
# an unknown key id refetches the key set at most this often, so forged tokens cannot make each call fetch it
JWKS_REFETCH_INTERVAL_SECONDS = 60
JWKS_FETCH_TIMEOUT_SECONDS = 5
# while Auth0 cannot be reached the last key set keeps verifying, but not longer than this: a key Auth0 retired in
# the meantime (a leaked one) must not verify tokens for the whole outage
JWKS_MAX_STALE_SECONDS = 24 * 60 * 60
CLOCK_LEEWAY_SECONDS = 60


class TokenRefusedError(Exception):
    """The call's token is missing or not a valid workflows modules token."""


class VerificationUnavailableError(Exception):
    """The token cannot be verified: Auth0's key set or the JWT library is unavailable."""


def read_regional_variables() -> Dict[str, Optional[str]]:
    """
    Read the regional variables file of a managed connector.

    Returns:
        Its variables, or an empty dict where it is not mounted (a private app, a local run).
    """
    environment = os.getenv("ENVIRONMENT", "").lower()
    region = os.getenv("REGION", "").lower()
    if not environment or not region:
        return {}
    path = os.path.join(os.getcwd(), "environment_variables", "regional", f"variables_{environment}_{region}.env")
    if not os.path.isfile(path):
        return {}
    try:
        return dotenv_values(path)
    except Exception as error:
        logger.warning(f"Module authentication: the regional variables file could not be read: {error}")
        return {}


def drain_request_body() -> None:
    """
    Read and drop the current request's body before a refusal is answered.

    The refusal is sent before the route reads the body; with bytes still unread, gunicorn's sync worker closes the
    socket, the kernel answers with a TCP reset and Cloud Run reports a 502 instead of the 401 or 503.
    """
    try:
        while request.stream.read(64 * 1024):
            pass
    except Exception as error:
        logger.warning(f"Module authentication: the refused request's body could not be read: {error}")


class ModuleAuthenticator:
    """Checks the workflows modules token of a call, with the mode and Auth0 settings read once at start."""

    def __init__(self, settings: Optional[Dict[str, Optional[str]]] = None) -> None:
        """
        Args:
            settings: The settings to use instead of the environment and the regional variables file (tests).
        """
        if settings is None:
            settings = {**read_regional_variables(), **os.environ}
        mode = (settings.get(MODE_SETTING_NAME) or OFF_MODE).strip().lower()
        if mode not in MODES:
            # a typo must neither turn the check off without a word nor refuse every call: the calls are logged
            logger.warning(f"Module authentication: unknown {MODE_SETTING_NAME} {mode!r}, using {LOG_MODE!r}")
            mode = LOG_MODE
        self.mode = mode
        default_domain, default_audience = DEFAULT_AUTH0_SETTINGS_BY_ENVIRONMENT[get_environment()]
        self.auth0_domain = settings.get(AUTH0_DOMAIN_SETTING_NAME) or default_domain
        self.auth0_audience = settings.get(AUTH0_AUDIENCE_SETTING_NAME) or default_audience
        self.key_set = None
        self.key_set_fetched_at = 0.0
        self.key_set_attempted_at = None
        self.key_set_lock = threading.Lock()

    def fetch_key_set_document(self) -> dict:
        """
        Fetch Auth0's public key set.

        Returns:
            The JWKS document.
        """
        url = f"https://{self.auth0_domain}/.well-known/jwks.json"
        with urllib.request.urlopen(url, timeout=JWKS_FETCH_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())

    def get_key_set(self, refetch: bool = False):
        """
        Auth0's key set, cached.

        Args:
            refetch: Fetch it again (a token signed with a key id the cached set does not hold), at most once a minute.

        Returns:
            The authlib KeySet.

        Raises:
            VerificationUnavailableError: When no key set was ever fetched and it cannot be now.
        """
        from authlib.jose import JsonWebKey

        with self.key_set_lock:
            now = time.monotonic()
            age = now - self.key_set_fetched_at
            is_stale = self.key_set is None or age > JWKS_LIFETIME_SECONDS or (refetch and age > JWKS_REFETCH_INTERVAL_SECONDS)
            # Every attempt, failed ones too, waits out the interval: an unreachable Auth0 must not make each call
            # wait for a fetch while the cached keys still verify
            may_attempt = self.key_set_attempted_at is None or now - self.key_set_attempted_at >= JWKS_REFETCH_INTERVAL_SECONDS
            if is_stale and may_attempt:
                self.key_set_attempted_at = now
                try:
                    self.key_set = JsonWebKey.import_key_set(self.fetch_key_set_document())
                    self.key_set_fetched_at = time.monotonic()
                except Exception as error:
                    if self.key_set is None:
                        raise VerificationUnavailableError(f"Auth0's key set could not be fetched: {error}") from error
                    # Auth0 unreachable: the last key set stays in use
                    logger.warning(f"Module authentication: Auth0's key set could not be refreshed: {error}")
            if self.key_set is None:
                raise VerificationUnavailableError("Auth0's key set could not be fetched; the next attempt waits out the interval")
            if time.monotonic() - self.key_set_fetched_at > JWKS_MAX_STALE_SECONDS:
                raise VerificationUnavailableError("Auth0's key set has not been refreshed for a day; cached keys are no longer used")
            return self.key_set

    def verify_token(self, token: str) -> None:
        """
        Verify a workflows modules token: RS256, signed by Auth0, issued for this environment's modules API, unexpired.

        Args:
            token: The bearer token.

        Raises:
            TokenRefusedError: When it is not a valid token.
            VerificationUnavailableError: When it cannot be verified.
        """
        try:
            from authlib.jose import JsonWebToken
            from authlib.jose.errors import JoseError
        except ImportError as error:
            raise VerificationUnavailableError("authlib is not installed") from error

        claims_options = {
            "iss": {"essential": True, "value": f"https://{self.auth0_domain}/"},
            "aud": {"essential": True, "value": self.auth0_audience},
            "exp": {"essential": True},
        }
        json_web_token = JsonWebToken(["RS256"])
        for refetch in (False, True):
            try:
                claims = json_web_token.decode(token, self.get_key_set(refetch=refetch), claims_options=claims_options)
                claims.validate(leeway=CLOCK_LEEWAY_SECONDS)
                return
            except VerificationUnavailableError:
                raise
            except (JoseError, ValueError) as error:
                # authlib answers a key id missing from the set with ValueError: the key set may have rotated
                if refetch or not isinstance(error, ValueError):
                    raise TokenRefusedError(f"invalid token: {type(error).__name__}") from error
            except Exception as error:
                raise TokenRefusedError(f"invalid token: {type(error).__name__}") from error

    def check_request(self):
        """
        Check the current request's token as the mode says.

        Returns:
            None to let the call run, or the 401 or 503 response that refuses it (enforce mode only).
        """
        if self.mode == OFF_MODE:
            return None
        authorization = request.headers.get("Authorization", "")
        try:
            if not authorization.startswith("Bearer ") or not authorization[len("Bearer "):].strip():
                raise TokenRefusedError("no bearer token")
            self.verify_token(authorization[len("Bearer "):].strip())
            return None
        except (TokenRefusedError, VerificationUnavailableError) as error:
            forwarded_for = request.headers.get("X-Forwarded-For", request.remote_addr or "")
            logger.warning(
                f"Module authentication ({self.mode}): {request.method} {request.path} {error}; "
                f"from {forwarded_for.split(',')[0].strip()} user-agent {request.headers.get('User-Agent', '')!r}"
            )
            if self.mode != ENFORCE_MODE:
                return None
            drain_request_body()
            if isinstance(error, VerificationUnavailableError):
                return jsonify({"error": "Service Unavailable", "message": "The caller's token could not be verified"}), 503
            return jsonify({"error": "Unauthorized", "message": "A valid Stacksync token is required"}), 401, {"WWW-Authenticate": "Bearer"}
