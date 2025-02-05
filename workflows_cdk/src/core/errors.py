"""
Simplified error handling with automatic logging and Sentry integration.
"""

import logging
import traceback
from typing import Any, Dict, Optional
import pkg_resources

import sentry_sdk


logger = logging.getLogger(__name__)

# Get CDK version
try:
    CDK_VERSION = pkg_resources.get_distribution("workflows-cdk").version
except Exception:
    CDK_VERSION = "unknown"


class ManagedError(Exception):
    """Base class for managed errors."""
    
    def __init__(
        self,
        message: str,
        error_type: str = "error",
        data: Optional[Dict[str, Any]] = None
    ):
        """Initialize error.
        
        Args:
            message: Error message
            error_type: Type of error
            data: Additional error data
        """
        super().__init__(message)
        self.error_type = error_type
        self.data = data or {}
        self.metadata = {
            "cdk_version": CDK_VERSION,
        }
        
        # Automatically log and send to Sentry
        self._log_error()
    
    def _log_error(self):
        """Log error locally and to Sentry."""
        # Log locally with traceback
        logger.error(
            f"Managed error: {self.message}",
            extra={
                "data": self.data,
                "metadata": self.metadata,
                "traceback": traceback.format_exc()
            }
        )
        
        # Send to Sentry
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("cdk_version", CDK_VERSION)
            for key, value in self.data.items():
                scope.set_extra(key, value)
            for key, value in self.metadata.items():
                scope.set_tag(key, value)
            sentry_sdk.capture_exception(self)
    
    @classmethod
    def validation_error(
        cls,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> "ManagedError":
        """Create a validation error."""
        return cls(message, "validation_error", data)
    
    @classmethod
    def service_error(
        cls,
        service: str,
        message: str,
        exc_info: Optional[Exception] = None
    ) -> "ManagedError":
        """Create a service error."""
        data = {
            "service": service
        }
        if exc_info:
            data["exc_info"] = {
                "type": type(exc_info).__name__,
                "message": str(exc_info)
            }
        return cls(message, "service_error", data)
    
    @classmethod
    def not_found_error(
        cls,
        resource: str,
        identifier: str
    ) -> "ManagedError":
        """Create a not found error."""
        return cls(
            f"{resource} not found: {identifier}",
            "not_found_error",
            {"resource": resource, "identifier": identifier}
        ) 