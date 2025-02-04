"""
Core functionality for Stacksync Workflows CDK.
Provides base classes and utilities for connector development.
"""

from .connector import BaseConnector
from .schema import SchemaManager
from .router import ConnectorRouter
from .types import (
    ConnectorResponse,
    SchemaResponse,
    ExecuteResponse,
    ContentResponse,
    ConnectorConfig,
)

__all__ = [
    "BaseConnector",
    "SchemaManager",
    "ConnectorRouter",
    "ConnectorResponse",
    "SchemaResponse",
    "ExecuteResponse",
    "ContentResponse",
    "ConnectorConfig",
] 