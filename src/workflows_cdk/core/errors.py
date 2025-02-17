"""
Simplified error handling with automatic logging and Sentry integration.
"""

import logging
import traceback
from typing import Any, Dict, Optional, Union
import pkg_resources
from dataclasses import dataclass, field

import sentry_sdk

logger = logging.getLogger(__name__)

# Get CDK version
try:
    CDK_VERSION = pkg_resources.get_distribution("workflows-cdk").version
except Exception:
    CDK_VERSION = "unknown"

@dataclass
class ManagedError(Exception):
    """Base class for managed application errors."""
    error: Union[str, Exception]
    data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    status_code: int = 400

    def __post_init__(self):
        """Initialize default values for optional fields."""
        self.data = self.data if self.data is not None else {}
        self.metadata = self.metadata if self.metadata is not None else {}

    def __str__(self) -> str:
        """Return string representation of the error."""
        return str(self.error)

    @classmethod
    def validation_error(
        cls,
        error: str,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ManagedError":
        """Create a validation error."""
        return cls(
            error=error,
            data=data,
            metadata=metadata,
            status_code=400
        )


    @classmethod
    def not_found(
        cls,
        resource: str,
        identifier: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ManagedError":
        """Create a not found error."""
        return cls(
            error=f"{resource} not found: {identifier}",
            data={"resource": resource, "identifier": identifier},
            metadata=metadata,
            status_code=404
        )

    @classmethod
    def unauthorized(
        cls,
        message: str = "Unauthorized access",
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ManagedError":
        """Create an unauthorized error."""
        return cls(
            error=message,
            metadata=metadata,
            status_code=401
        )

    @classmethod
    def forbidden(
        cls,
        message: str = "Access forbidden",
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ManagedError":
        """Create a forbidden error."""
        return cls(
            error=message,
            metadata=metadata,
            status_code=403
        )

    @classmethod
    def server_error(
        cls,
        error: Union[str, Exception],
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ManagedError":
        """Create a server error."""
        return cls(
            error=error,
            metadata=metadata,
            status_code=500
        )

    def _log_error(self):
        """Log error locally and to Sentry."""
        # Log locally with all context
        logger.error(
            f"Managed error: {self.error}",
            extra={
                "data": self.data,
                "metadata": self.metadata
            }
        )
        
        # Send to Sentry with full context
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("cdk_version", CDK_VERSION)
            
            # Add data as extras
            if self.data:
                scope.set_extra("error_data", self.data)
                
            # Add metadata as tags and extras
            if self.metadata:
                for key, value in self.metadata.items():
                    if isinstance(value, (str, int, float, bool)):
                        scope.set_tag(key, value)
                    else:
                        scope.set_extra(key, value)
                        
            sentry_sdk.capture_exception(self)
    
    @classmethod
    def service_error(
        cls,
        error: Any,
        service: str,
        data: Optional[Any] = None
    ) -> "ManagedError":
        """Create a service error."""
        return cls(
            error=error,
            data=data,
            metadata={
                "error_type": "service",
                "service": service
            }
        )
    
    @classmethod
    def not_found_error(
        cls,
        error: Any,
        resource: str,
        identifier: str
    ) -> "ManagedError":
        """Create a not found error."""
        return cls(
            error=error,
            data={"identifier": identifier},
            metadata={
                "error_type": "not_found",
                "resource": resource
            }
        ) 