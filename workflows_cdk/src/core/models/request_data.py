"""
Enhanced request data handling with automatic validation and intellisense support.
"""

from typing import Any, Dict, Optional, TypeVar, Generic
from pydantic import BaseModel, Field


T = TypeVar('T')


class WorkflowCredentials(BaseModel):
    """Standardized workflow credentials model."""
    user_id: str = Field(..., description="User ID")
    workspace_id: str = Field(..., description="Workspace ID")
    connector_id: str = Field(..., description="Connector ID")
    access_token: Optional[str] = Field(None, description="Access token if required")
    refresh_token: Optional[str] = Field(None, description="Refresh token if required")
    custom: Dict[str, Any] = Field(default_factory=dict, description="Custom credentials")

    def get_token(self, key: str = "access_token") -> Optional[str]:
        """Get token from credentials.
        
        Args:
            key: Key to look for token (access_token, refresh_token, or custom key)
        """
        if key in ("access_token", "refresh_token"):
            return getattr(self, key)
        return self.custom.get(key)


class WorkflowData(BaseModel, Generic[T]):
    """Standardized workflow data model."""
    input: T = Field(..., description="Input data for the operation")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the operation"
    )

    def get_input(self, key: str, default: Any = None) -> Any:
        """Safely get input value."""
        if isinstance(self.input, dict):
            return self.input.get(key, default)
        return getattr(self.input, key, default)


class WorkflowRequest(BaseModel, Generic[T]):
    """Enhanced workflow request model with validation and easy access."""
    data: WorkflowData[T] = Field(..., description="Request data")
    credentials: WorkflowCredentials = Field(..., description="Request credentials")
    
    @property
    def input(self) -> T:
        """Easy access to input data."""
        return self.data.input
        
    @property
    def metadata(self) -> Dict[str, Any]:
        """Easy access to metadata."""
        return self.data.metadata
        
    @property
    def user_id(self) -> str:
        """Easy access to user ID."""
        return self.credentials.user_id
        
    @property
    def workspace_id(self) -> str:
        """Easy access to workspace ID."""
        return self.credentials.workspace_id
        
    @property
    def connector_id(self) -> str:
        """Easy access to connector ID."""
        return self.credentials.connector_id
        
    def get_token(self, key: str = "access_token") -> Optional[str]:
        """Get authentication token."""
        return self.credentials.get_token(key)
        
    def validate_required(self, *fields: str) -> None:
        """Validate required fields exist in input.
        
        Args:
            *fields: Field names to validate
            
        Raises:
            ValueError: If any required field is missing
        """
        missing = []
        for field in fields:
            if not self.data.get_input(field):
                missing.append(field)
                
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}") 