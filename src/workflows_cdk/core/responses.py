"""
Standardized API responses for workflow operations.
"""

from typing import Any, Dict, Optional, Union
from datetime import datetime
from flask import jsonify, make_response, Response as FlaskResponse

from .errors import ManagedError


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
        response = {
            "status": "success",
            "message": message,
            "data": data
        }
        
        if metadata:
            response["metadata"] = metadata
            
        return make_response(jsonify(response), status_code)
    
    @staticmethod
    def error(
        error: Union[ManagedError, Exception, str],
        status_code: int = 400
    ) -> FlaskResponse:
        """Create an error response.
        
        Args:
            error: Error object or message
            status_code: HTTP status code
        """
        if isinstance(error, ManagedError):
            response = {
                "status": "error",
                "error": error.error,
                "data": error.data,
                "metadata": error.metadata
            }
        elif isinstance(error, Exception):
            response = {
                "status": "error",
                "error": str(error),
                "data": {
                    "exception_type": type(error).__name__
                },
                "metadata": {
                    "traceback": str(error.__traceback__)
                }
            }
        else:
            response = {
                "status": "error",
                "error": str(error)
            }
            
        return make_response(jsonify(response), status_code)
