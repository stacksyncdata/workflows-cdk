"""
Errors shown to the user. A ManagedError is never sent to Sentry: the Router logs it as a
warning (see wrap_route_handler), because it describes the user's input or connection, not a bug.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ManagedError(Exception):
    """Base class for managed application errors."""

    error: str | Exception
    data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
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
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ManagedError":
        """Create a validation error."""
        return cls(error=error, data=data, metadata=metadata, status_code=400)

    @classmethod
    def not_found(
        cls, resource: str, identifier: Any, metadata: dict[str, Any] | None = None
    ) -> "ManagedError":
        """Create a not found error."""
        return cls(
            error=f"{resource} not found: {identifier}",
            data={"resource": resource, "identifier": identifier},
            metadata=metadata,
            status_code=404,
        )

    @classmethod
    def unauthorized(
        cls,
        message: str = "Unauthorized access",
        metadata: dict[str, Any] | None = None,
    ) -> "ManagedError":
        """Create an unauthorized error."""
        return cls(error=message, metadata=metadata, status_code=401)

    @classmethod
    def forbidden(
        cls,
        message: str = "Access forbidden",
        metadata: dict[str, Any] | None = None,
    ) -> "ManagedError":
        """Create a forbidden error."""
        return cls(error=message, metadata=metadata, status_code=403)

    @classmethod
    def server_error(
        cls, error: str | Exception, metadata: dict[str, Any] | None = None
    ) -> "ManagedError":
        """Create a server error."""
        return cls(error=error, metadata=metadata, status_code=500)

    @classmethod
    def service_error(
        cls, error: Any, service: str, data: Any | None = None
    ) -> "ManagedError":
        """Create a service error."""
        return cls(
            error=error,
            data=data,
            metadata={"error_type": "service", "service": service},
        )

    @classmethod
    def not_found_error(
        cls, error: Any, resource: str, identifier: str
    ) -> "ManagedError":
        """Create a not found error."""
        return cls(
            error=error,
            data={"identifier": identifier},
            metadata={"error_type": "not_found", "resource": resource},
        )
