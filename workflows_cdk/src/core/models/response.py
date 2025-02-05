"""
Standard response models for the Workflows CDK.
"""

from typing import Any, Dict, Generic, Optional, TypeVar
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


T = TypeVar('T')


class ResponseStatus(str, Enum):
    """Standard response status values."""
    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ManagedError(BaseModel):
    """Standardized error model."""
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    severity: ErrorSeverity = Field(default=ErrorSeverity.ERROR)
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    suggestion: Optional[str] = Field(None, description="Suggested fix if available")
    docs_url: Optional[str] = Field(None, description="Link to relevant documentation")


class ResponseMetadata(BaseModel):
    """Standard response metadata."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = Field(None, description="Original request ID")
    version: str = Field(..., description="API version")
    operation: str = Field(..., description="Operation performed")
    duration_ms: Optional[float] = Field(None, description="Operation duration in milliseconds")
    cache_hit: Optional[bool] = Field(None, description="Whether result was from cache")
    rate_limit: Optional[Dict[str, Any]] = Field(None, description="Rate limit information")


class Response(BaseModel, Generic[T]):
    """Standard response model with typed data."""
    status: ResponseStatus = Field(..., description="Response status")
    data: Optional[T] = Field(None, description="Response data")
    metadata: ResponseMetadata = Field(..., description="Response metadata")
    error: Optional[ManagedError] = Field(None, description="Error information if status is error")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        
    @classmethod
    def success(
        cls,
        data: T,
        metadata: Optional[ResponseMetadata] = None,
        **kwargs
    ) -> "Response[T]":
        """Create a success response."""
        if not metadata:
            metadata = ResponseMetadata(**kwargs)
        return cls(
            status=ResponseStatus.SUCCESS,
            data=data,
            metadata=metadata
        )
        
    @classmethod
    def error(
        cls,
        error: ManagedError,
        metadata: Optional[ResponseMetadata] = None,
        **kwargs
    ) -> "Response[T]":
        """Create an error response."""
        if not metadata:
            metadata = ResponseMetadata(**kwargs)
        return cls(
            status=ResponseStatus.ERROR,
            error=error,
            metadata=metadata
        ) 