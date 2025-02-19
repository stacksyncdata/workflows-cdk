"""
Response handling module for Flask applications.
Provides standardized response formatting and error handling.
"""

from typing import Any, Dict, Optional, Union
from datetime import datetime
from flask import jsonify, make_response, Response as FlaskResponse
import os
from werkzeug.exceptions import HTTPException
from workflows_cdk.core.errors import ManagedError


class Response:
    """Standardized response class for API endpoints."""
    
    # Cache environment check
    _IS_PRODUCTION = os.getenv("ENVIRONMENT", "").lower() == "prod"
    
    @classmethod
    def success(
        cls,
        data: Any = None,
        message: str = "Success",
        metadata: Optional[Dict[str, Any]] = None,
        status_code: int = 200
    ) -> FlaskResponse:
        """Create a success response."""
        response_data = {
            "status": "success",
            "message": message,
            "data": data
        }
        
        if metadata:
            response_data["metadata"] = metadata
            
        return make_response(jsonify(response_data), status_code)
    
    @classmethod
    def error(
        cls,
        error: Union[ManagedError, Exception, str],
        status_code: int = 400
    ) -> FlaskResponse:
        """Create an error response with environment-appropriate detail level."""
       
        
        # Get stack trace for non-production environments
        stack_trace = None
        if not cls._IS_PRODUCTION and isinstance(error, Exception):
            import traceback
            stack_trace = traceback.format_exc()
        
        # Base metadata
        base_metadata = {
            "timestamp": datetime.now().isoformat(),
            "environment": os.getenv("ENVIRONMENT", "development"),
            # "event_id": event_id,
            "stack_trace": stack_trace
        }
        
        # Merge with error metadata if available
        metadata = base_metadata
        if isinstance(error, ManagedError) and error.metadata:
            metadata = {**base_metadata, **error.metadata}
        
        if isinstance(error, ManagedError):
            response_data = {
                "status": "error",
                "error": str(error.error),
                "data": error.data,
                "metadata": metadata
            }
        elif isinstance(error, HTTPException):
            status_code = error.code or status_code
            response_data = {
                "status": "error",
                "error": error.description,
                "data": {"code": error.code, "name": error.name},
                "metadata": metadata
            }
        else:
            response_data = {
                "status": "error",
                "error": str(error),
                "data": {"error_type": type(error).__name__ if isinstance(error, Exception) else "string"},
                "metadata": metadata
            }
            
        return make_response(jsonify(response_data), status_code)
