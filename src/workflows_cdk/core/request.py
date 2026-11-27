"""Request handling for the Workflows CDK."""

from typing import Any

from flask import Request as FlaskRequest


class Request:
    """Wrapper for Flask request that adds workflow-specific functionality.

    Usage:
        @router.route("/execute", methods=["POST"])
        def execute():
            request_data = Request(flask_request)
            data = request_data.data
            credentials = request_data.credentials.connection_data.value
    """

    def __init__(self, flask_request: FlaskRequest):
        """Initialize with a Flask request instance."""
        self._request = flask_request
        self._json_data = None

    @property
    def request_data(self) -> dict[str, Any]:
        """Get the request data."""
        return self.json

    @property
    def json(self) -> dict[str, Any]:
        """Get the cached JSON data from the request."""
        if self._json_data is None:
            request_json = self._request.get_json(silent=True)
            # Only an object body has data/credentials; any other JSON value reads as empty
            self._json_data = request_json if isinstance(request_json, dict) else {}
        return self._json_data

    @property
    def data(self) -> dict[str, Any]:
        """Get the data portion of the request.

        Returns:
            dict[str, Any]: The data portion of the request
        """
        return self.json.get("data", {})

    @property
    def credentials(self) -> dict[str, Any]:
        """Get the credentials from the request.

        Returns:
            dict[str, Any]: The credentials from the request
        """
        # `or {}` on each level: a null level must not raise AttributeError here, because Python
        # would then fall back to __getattr__ and report "'Request' object has no attribute 'credentials'"
        credentials = self.json.get("credentials") or {}
        connection_data = credentials.get("connection_data") or {}
        return connection_data.get("value") or {}

    def __getattr__(self, name: str) -> Any:
        """Delegate any unknown attributes to the underlying Flask request."""
        return getattr(self._request, name)
