"""
Schema management system for Stacksync Workflows CDK.
Handles schema versioning, validation, and caching.
"""

from typing import Any, Dict, List, Optional, Type
from functools import lru_cache
import json
from datetime import datetime

from pydantic import ValidationError, create_model

from .types import (
    SchemaField,
    SchemaResponse,
    ConnectorConfig,
)


class SchemaManager:
    """Manages connector schemas including versioning and validation."""
    
    def __init__(self, config: ConnectorConfig):
        """Initialize the schema manager.
        
        Args:
            config: Connector configuration
        """
        self.config = config
        self._schema_cache = {}
        self._validation_models = {}
        
    def register_schema(
        self,
        schema: Dict[str, List[SchemaField]],
        ui_schema: Optional[Dict[str, Any]] = None,
        version: Optional[str] = None
    ) -> None:
        """Register a new schema version.
        
        Args:
            schema: Schema definition
            ui_schema: Optional UI schema for form rendering
            version: Schema version (defaults to config version)
        """
        version = version or self.config.version
        
        # Create Pydantic model for validation
        fields = {}
        for section, section_fields in schema.items():
            for field in section_fields:
                python_type = self._get_python_type(field)
                fields[field.name] = (python_type, field.dict())
                
        model = create_model(f"SchemaModel_{version}", **fields)
        
        self._validation_models[version] = model
        self._schema_cache[version] = {
            "schema": schema,
            "ui_schema": ui_schema or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        
    @lru_cache(maxsize=128)
    def get_schema(self, version: Optional[str] = None) -> SchemaResponse:
        """Get schema by version.
        
        Args:
            version: Schema version (defaults to latest)
            
        Returns:
            SchemaResponse with schema data
            
        Raises:
            KeyError: If version doesn't exist
        """
        version = version or self.config.version
        if version not in self._schema_cache:
            raise KeyError(f"Schema version {version} not found")
            
        cached = self._schema_cache[version]
        return SchemaResponse(
            status="success",
            data=cached["schema"],
            ui_schema=cached["ui_schema"],
            version=version
        )
        
    def validate_data(self, data: Dict[str, Any], version: Optional[str] = None) -> Dict[str, Any]:
        """Validate data against schema.
        
        Args:
            data: Data to validate
            version: Schema version to validate against
            
        Returns:
            Validated and potentially coerced data
            
        Raises:
            ValidationError: If validation fails
        """
        version = version or self.config.version
        if version not in self._validation_models:
            raise KeyError(f"Schema version {version} not found")
            
        model = self._validation_models[version]
        validated = model(**data)
        return validated.dict()
        
    @staticmethod
    def _get_python_type(field: SchemaField) -> Type:
        """Get Python type for schema field type."""
        type_mapping = {
            "text": str,
            "number": float,
            "boolean": bool,
            "select": str,
            "multi_select": List[str],
            "date": str,  # ISO format
            "datetime": str,  # ISO format
            "file": Dict[str, Any],  # File metadata
            "json": Dict[str, Any],
        }
        return type_mapping.get(field.type, Any)
        
    def clear_cache(self) -> None:
        """Clear schema cache."""
        self._schema_cache.clear()
        self._validation_models.clear()
        self.get_schema.cache_clear() 