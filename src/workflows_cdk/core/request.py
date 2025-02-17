"""Request handling for the Workflows CDK."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from flask import Request as FlaskRequest
from flask import request as flask_request
from werkzeug.local import LocalProxy

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
    def request_data(self) -> Dict[str, Any]:
        """Get the request data."""
        return self.json

    @property
    def json(self) -> Dict[str, Any]:
        """Get the cached JSON data from the request."""
        if self._json_data is None:
            self._json_data = self._request.get_json(silent=True) or {}
        return self._json_data

    @property
    def data(self) -> Dict[str, Any]:
        """Get the data portion of the request.
        
        Returns:
            Dict[str, Any]: The data portion of the request
        """
        return self.json.get("data", {})

    @property
    def credentials(self) -> Dict[str, Any]:
        """Get the credentials from the request.
        
        Returns:
            Dict[str, Any]: The credentials from the request
        """
        return self.json.get("credentials", {}).get("connection_data", {}).get("value", {})

    def __getattr__(self, name: str) -> Any:
        """Delegate any unknown attributes to the underlying Flask request."""
        return getattr(self._request, name)

