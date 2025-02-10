"""
Simplified error handling with automatic logging and Sentry integration.
"""

import logging
import traceback
from typing import Any, Dict, Optional, TypedDict
import pkg_resources

import sentry_sdk


logger = logging.getLogger(__name__)

# Get CDK version
try:
    CDK_VERSION = pkg_resources.get_distribution("workflows-cdk").version
except Exception:
    CDK_VERSION = "unknown"


class ErrorData(TypedDict, total=False):
    """Type definition for error data."""
    type: str
    message: str
    service: str
    identifier: str
    exc_info: Dict[str, str]

class ManagedError(Exception):
    """Base class for managed errors."""
    
    def __init__(
        self,
        error: Optional[Any] = None,
        data: Optional[Any] = None,
        metadata: Optional[Any] = None
    ):
        """Initialize error.
        
        Args:
            error: Error message
            data: Additional error data (can be any type)
            metadata: Metadata about the error (can be any type)
        """
        super().__init__(error)
        self._message = error  # Store message separately
        self._error = error  # Use private attribute to avoid property conflict
        self.data = data
        self.metadata = metadata or {}
        self.metadata["cdk_version"] = CDK_VERSION
        # Automatically log and send to Sentry
        self._log_error()
    
    @property
    def error(self) -> str:
        """Get error message."""
        return self.error
    
    def _log_error(self):
        """Log error locally and to Sentry."""
        # Log locally with traceback
        logger.error(
            f"Managed error: {self.error}",
            extra={
                "data": self.data,
                "metadata": self.metadata,
                "traceback": traceback.format_exc()
            }
        )
        
        # Send to Sentry
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("cdk_version", CDK_VERSION)
            if self.data:
                for key, value in self.data.items():
                    scope.set_extra(key, value)
            if self.metadata:
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
        data: ErrorData = {
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