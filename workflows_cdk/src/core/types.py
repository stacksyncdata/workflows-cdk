"""
Type definitions for the Stacksync Workflows CDK.
"""

from typing import Any, Dict, List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field


class SchemaFieldType(str, Enum):
    """Available field types for schema definitions."""
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    DATE = "date"
    DATETIME = "datetime"
    FILE = "file"
    JSON = "json"


class SchemaField(BaseModel):
    """Definition of a schema field."""
    name: str = Field(..., description="Field identifier")
    type: SchemaFieldType = Field(..., description="Field type")
    label: str = Field(..., description="Human-readable label")
    description: Optional[str] = Field(None, description="Field description")
    required: bool = Field(default=False, description="Whether the field is required")
    default: Optional[Any] = Field(None, description="Default value")
    options: Optional[List[Dict[str, str]]] = Field(None, description="Options for select fields")
    validation: Optional[Dict[str, Any]] = Field(None, description="Validation rules")


class ConnectorConfig(BaseModel):
    """Configuration for a connector instance."""
    version: str = Field(..., description="Connector version")
    name: str = Field(..., description="Connector name")
    description: str = Field(..., description="Connector description")
    author: str = Field(..., description="Connector author")
    base_url: Optional[str] = Field(None, description="Base URL for the connector")
    auth_required: bool = Field(default=False, description="Whether authentication is required")
    auth_type: Optional[str] = Field(None, description="Authentication type if required")


class BaseResponse(BaseModel):
    """Base response model for all connector responses."""
    status: str = Field(..., description="Response status")
    message: Optional[str] = Field(None, description="Response message")
    error: Optional[str] = Field(None, description="Error message if any")


class SchemaResponse(BaseResponse):
    """Response model for schema endpoint."""
    data: Dict[str, List[SchemaField]] = Field(..., description="Schema definition")
    ui_schema: Optional[Dict[str, Any]] = Field(None, description="UI schema for form rendering")
    version: str = Field(..., description="Schema version")


class ExecuteResponse(BaseResponse):
    """Response model for execute endpoint."""
    data: Dict[str, Any] = Field(..., description="Execution results")
    execution_id: str = Field(..., description="Unique execution identifier")


class ContentResponse(BaseResponse):
    """Response model for content endpoint."""
    data: Any = Field(..., description="Content data")
    content_type: str = Field(..., description="Content type identifier")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


ConnectorResponse = Union[SchemaResponse, ExecuteResponse, ContentResponse] 