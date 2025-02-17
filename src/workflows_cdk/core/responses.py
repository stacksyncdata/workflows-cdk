"""
Standardized API responses for workflow operations.
"""

from typing import Any, Dict, Optional, Union
from datetime import datetime
from flask import jsonify, make_response, Response as FlaskResponse, current_app
import traceback
import os
import sentry_sdk

from .errors import ManagedError


class Response:
    """Standardized response handling."""
    
    @staticmethod
    def _is_production() -> bool:
        """Check if we're running in production environment."""
        return os.getenv("ENVIRONMENT", "").lower() == "prod"

    
    @staticmethod
    def _get_sanitized_error(error: Union[ManagedError, Exception, str]) -> Dict[str, Any]:
        """Get a sanitized error response for production environment."""
        if isinstance(error, ManagedError):
            # For managed errors, show all information except traceback
            return {
                "status": "error",
                "error": error.error,
                "data": error.data,
                "metadata": {
                    **error.metadata,
                    "error_type": type(error).__name__,
                    "timestamp": datetime.now().isoformat()
                }
            }
        elif isinstance(error, Exception):
            # Get the existing Sentry event ID from the current scope
            # event_id = sentry_sdk.last_event_id()
            event_id = None
            # For unhandled exceptions, show error details but no traceback
            error_chain = []
            current = error
            while current is not None:
                error_chain.append({
                    "type": type(current).__name__,
                    "message": str(current)
                })
                current = current.__cause__ or current.__context__

            return {
                "status": "error",
                "error": str(error),
                "data": {
                    "exception_type": type(error).__name__,
                    "error_chain": error_chain,
                    "event_error_id": event_id,
                    "timestamp": datetime.now().isoformat()
                },
                "metadata": {
                    "environment": os.getenv("ENVIRONMENT", "production")
                }
            }
        else:
            return {
                "status": "error",
                "error": str(error),
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "error_type": "string"
                }
            }
    
    @staticmethod
    def _get_detailed_error(error: Union[ManagedError, Exception, str], tb: str) -> Dict[str, Any]:
        """Get a detailed error response for non-production environments."""
        if isinstance(error, ManagedError):
            return {
                "status": "error",
                "error": error.error,
                "data": error.data,
                "metadata": {
                    **error.metadata,
                    "traceback": tb.split('\n'),
                    "error_type": type(error).__name__
                }
            }
        elif isinstance(error, Exception):
            # Extract the full exception chain
            error_chain = []
            current = error
            while current is not None:
                error_chain.append({
                    "type": type(current).__name__,
                    "message": str(current)
                })
                current = current.__cause__ or current.__context__
            
            return {
                "status": "error",
                "error": str(error),
                "data": {
                    "exception_type": type(error).__name__,
                    "error_chain": error_chain
                },
                "metadata": {
                    "traceback": tb.split('\n'),
                    "timestamp": datetime.now().isoformat(),
                    "environment": os.getenv("ENVIRONMENT", "development")
                }
            }
        else:
            return {
                "status": "error",
                "error": str(error),
                "metadata": {
                    "traceback": tb.split('\n'),
                    "environment": os.getenv("ENVIRONMENT", "development")
                }
            }
    
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
        """Create an error response with environment-appropriate detail level.
        
        In production, shows sanitized errors without implementation details.
        In non-production environments, shows detailed error information and stack traces.
        
        Args:
            error: Error object or message
            status_code: HTTP status code
        """
        # Get the full traceback for logging and non-prod environments
        tb = traceback.format_exc()
        
        # Always log the full error details regardless of environment
        if isinstance(error, Exception):
            current_app.logger.error(
                f"Error occurred: {str(error)}\n"
                f"Type: {type(error).__name__}\n"
                f"Traceback:\n{tb}"
            )
        
        # Determine response format based on environment
        if Response._is_production():
            response = Response._get_sanitized_error(error)
        else:
            response = Response._get_detailed_error(error, tb)
            
        return make_response(jsonify(response), status_code)
