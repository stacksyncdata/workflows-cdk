"""Request handling for the Workflows CDK."""

from typing import Any, Dict, Optional, cast, TypeVar, Type
from flask import request, Request as FlaskRequest
from werkzeug.datastructures import MultiDict, FileStorage, ImmutableMultiDict
from pydantic import BaseModel, field_validator
from functools import cached_property


class RequestData(BaseModel):
    """Model for validating and extracting request data."""
    data: Dict[str, Any] = {}
    credentials: Dict[str, Any] = {}

    @field_validator("credentials", mode="before")
    @classmethod
    def extract_credentials(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Extract credentials from the nested request structure."""
        credentials_holder = value.get("credentials", {})
        credentials_value = credentials_holder.get("connection_data", {}).get("value", {})
        return credentials_value.get("credentials", {})


T = TypeVar('T')

class Request:
    """Wrapper for incoming requests with additional context."""
    
    def __init__(self):
        """Initialize request object."""
        self.version: str = ""
        self.category: str = ""
        self.module_id: str = ""
        self.request_id: str = ""
        self.validated_data: Optional[Any] = None
        self._request_data: Optional[RequestData] = None
        
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

    @cached_property
    def _validated_data(self) -> RequestData:
        """Get validated request data using Pydantic model."""
        json_data = self.json
        return RequestData(
            data=json_data.get("data", {}),
            credentials=json_data.get("credentials", {})
        )

    @property
    def credentials(self) -> Dict[str, Any]:
        """Get validated credentials from the request."""
        return self._validated_data.credentials

    @property
    def data(self) -> Dict[str, Any]:
        """Get validated data from the request."""
        return self._validated_data.data
    
    @property
    def headers(self) -> Dict[str, str]:
        """Get request headers."""
        return dict(request.headers)
    
    @property
    def method(self) -> str:
        """Get request method."""
        return request.method
    
    @property
    def args(self) -> MultiDict[str, str]:
        """Get query parameters."""
        return request.args
    
    @property
    def files(self) -> ImmutableMultiDict[str, FileStorage]:
        """Get uploaded files."""
        return request.files
    
    @property
    def form(self) -> ImmutableMultiDict[str, str]:
        """Get form data."""
        return request.form

    def get_json(self, force: bool = False, silent: bool = False, cache: bool = True) -> Optional[Dict[str, Any]]:
        """Get JSON data from request."""
        return request.get_json(force=force, silent=silent, cache=cache) 