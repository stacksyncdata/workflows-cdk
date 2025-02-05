"""
Standard request models for the Workflows CDK.
"""

from typing import Any, Dict, Optional, TypeVar, Generic
from pydantic import BaseModel, Field


T = TypeVar('T')


class Credentials(BaseModel):
    """Standard credentials model."""
    api_key: Optional[str] = Field(None, description="API key if required")
    access_token: Optional[str] = Field(None, description="OAuth access token if required")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token if required")
    custom: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Custom credentials fields"
    )


class RequestContext(BaseModel):
    """Request context information."""
    connector_id: str = Field(..., description="Unique connector identifier")
    version: str = Field(..., description="API version")
    operation: str = Field(..., description="Operation being performed")
    trace_id: Optional[str] = Field(None, description="Request trace ID")
    user_id: Optional[str] = Field(None, description="User ID if available")
    workspace_id: Optional[str] = Field(None, description="Workspace ID if available")


class Request(BaseModel, Generic[T]):
    """Standard request model with typed data."""
    data: T = Field(..., description="Request data")
    credentials: Optional[Credentials] = Field(None, description="Authentication credentials")
    context: RequestContext = Field(..., description="Request context")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional request metadata"
    ) 