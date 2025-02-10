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
    """Base class for managed errors with consistent error handling."""
    
    def __init__(
        self,
        error: Any,
        data: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize error with consistent parameters.
        
        Args:
            error: Error message or object (can be any type)
            data: Additional error data (can be any type)
            metadata: Error metadata for debugging/tracking (dict)
        """
        super().__init__(str(error))
        self.error = error
        self.data = data
        self.metadata = metadata or {}
        
        # Add CDK version to metadata
        self.metadata["cdk_version"] = CDK_VERSION
        
        # Add traceback and locals to metadata if not present
        if "traceback" not in self.metadata:
            self.metadata["traceback"] = traceback.format_exc()
            
        # Get local variables at point of error
        try:
            frame = next(
                (frame for frame in traceback.extract_stack() if frame.filename != __file__),
                None
            )
            if frame:
                self.metadata["error_location"] = {
                    "file": frame.filename,
                    "line": frame.lineno,
                    "function": frame.name
                }
        except Exception:
            pass
            
        # Log error automatically
        self._log_error()
    
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
    def validation_error(cls, error: Any, data: Optional[Any] = None) -> "ManagedError":
        """Create a validation error."""
        return cls(
            error=error,
            data=data,
            metadata={"error_type": "validation"}
        )
    
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