"""Request handling for the Workflows CDK."""

from typing import Any, Dict, Optional
from flask import request, Request as FlaskRequest


class Request(FlaskRequest):
    """Wrapper for incoming requests with additional context."""
    
    def __init__(self):
        """Initialize request object."""
        self.version: str = ""
        self.category: str = ""
        self.module_id: str = ""
        self.request_id: str = ""
        self.validated_data: Optional[Any] = None
        
    @property
    def json(self) -> Dict[str, Any]:
        """Get JSON data from request."""
        return request.get_json(silent=True) or {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from JSON data."""
        return self.json.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        """Get a required value from JSON data."""
        try:
            return self.json[key]
        except KeyError:
            raise ValueError(f"Missing required field: {key}")
    
    @property
    def headers(self) -> Dict[str, str]:
        """Get request headers."""
        return dict(request.headers)
    
    @property
    def method(self) -> str:
        """Get request method."""
        return request.method
    
    @property
    def args(self) -> Dict[str, str]:
        """Get query parameters."""
        return dict(request.args)
    
    @property
    def files(self) -> Dict[str, Any]:
        """Get uploaded files."""
        return dict(request.files)
    
    @property
    def form(self) -> Dict[str, str]:
        """Get form data."""
        return dict(request.form) 