"""
Router system for Stacksync Workflows CDK.
Handles endpoint routing, request validation, and response formatting.
"""

from typing import Any, Callable, Dict, Optional, Type, Union, Tuple
from functools import wraps
import logging
from datetime import datetime
import uuid

from flask import Flask, request, jsonify, Response
from pydantic import ValidationError

from .types import (
    ConnectorResponse,
    SchemaResponse,
    ExecuteResponse,
    ContentResponse,
    ConnectorConfig,
)
from .schema import SchemaManager


logger = logging.getLogger(__name__)


def handle_errors(func: Callable) -> Callable:
    """Decorator for handling endpoint errors."""
    @wraps(func)
    def wrapper(*args, **kwargs) -> Response:
        try:
            result = func(*args, **kwargs)
            return jsonify(result.dict())
        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            return jsonify({
                "status": "error",
                "error": "Validation error",
                "message": str(e)
            }), 400
        except Exception as e:
            logger.exception("Unexpected error")
            return jsonify({
                "status": "error",
                "error": "Internal server error",
                "message": str(e)
            }), 500
    return wrapper


class ConnectorRouter:
    """Router for handling connector endpoints."""
    
    def __init__(
        self,
        config: ConnectorConfig,
        schema_manager: SchemaManager,
        app: Optional[Flask] = None
    ):
        """Initialize the router.
        
        Args:
            config: Connector configuration
            schema_manager: Schema manager instance
            app: Optional Flask app instance
        """
        self.config = config
        self.schema_manager = schema_manager
        self.app = app or Flask(__name__)
        self._setup_routes()
        
    def _setup_routes(self) -> None:
        """Set up default routes."""
        
        @self.app.route("/health", methods=["GET"])
        def health_check() -> Response:
            """Health check endpoint."""
            return jsonify({
                "status": "success",
                "message": "Service is healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "version": self.config.version
            })
            
        @self.app.route("/schema", methods=["GET"])
        @handle_errors
        def get_schema() -> SchemaResponse:
            """Get schema endpoint."""
            version = request.args.get("version")
            return self.schema_manager.get_schema(version)
            
    def register_execute_handler(
        self,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
        """Register execute endpoint handler.
        
        Args:
            handler: Function that processes execute requests
        """
        @self.app.route("/execute", methods=["POST"])
        @handle_errors
        def execute() -> ExecuteResponse:
            data = request.get_json()
            version = data.pop("version", None)
            
            # Validate input against schema
            validated_data = self.schema_manager.validate_data(data, version)
            
            # Execute handler
            result = handler(validated_data)
            
            return ExecuteResponse(
                status="success",
                data=result,
                execution_id=str(uuid.uuid4())
            )
            
    def register_content_handler(
        self,
        handler: Callable[[Dict[str, Any]], Tuple[Any, str, Dict[str, Any]]]
    ) -> None:
        """Register content endpoint handler.
        
        Args:
            handler: Function that processes content requests
        """
        @self.app.route("/content", methods=["POST"])
        @handle_errors
        def get_content() -> ContentResponse:
            data = request.get_json()
            
            # Execute handler
            content_data, content_type, metadata = handler(data)
            
            return ContentResponse(
                status="success",
                data=content_data,
                content_type=content_type,
                metadata=metadata
            )
            
    def run(self, host: str = "0.0.0.0", port: int = 5000, **kwargs) -> None:
        """Run the connector service.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            **kwargs: Additional arguments passed to Flask run
        """
        self.app.run(host=host, port=port, **kwargs) 