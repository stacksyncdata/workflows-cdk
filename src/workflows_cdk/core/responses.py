"""
Standardized API responses for workflow operations.
"""

from typing import Any, Dict, Optional, Union, TypedDict
from datetime import datetime
from flask import jsonify, make_response, Response as FlaskResponse

from .errors import ManagedError


class ResponseData(TypedDict, total=False):
    """Type definition for response data."""
    status: str
    message: str
    error: str
    data: Any
    metadata: Dict[str, Any]


class Response:
    """Standardized response handling."""
    
    @staticmethod
    def success(
        data: Any = None,
        message: str = "Success",
        metadata: Optional[Dict[str, Any]] = None,
        status_code: int = 200
    ) -> FlaskResponse:
        """Create a success response.
        
        Args:
            data: Response data
            message: Success message
            metadata: Optional metadata
            status_code: HTTP status code
        """
        response: ResponseData = {
            "status": "success",
            "message": message,
            "data": data
        }
        
        if metadata:
            response["metadata"] = metadata
            
        return make_response(jsonify(response), status_code)
    
    @staticmethod
    def error(
        error: Union[Exception, str],
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        status_code: int = 400
    ) -> FlaskResponse:
        """Create an error response.
        
        Args:
            error: Error object or message
            message: Optional error message override
            data: Additional error data
            status_code: HTTP status code
        """
        response: ResponseData = {
            "status": "error",
            "error": str(error),
            "message": message or str(error)
        }
        
        if data:
            response["data"] = data
            
        return make_response(jsonify(response), status_code)
