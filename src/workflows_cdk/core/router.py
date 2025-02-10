"""
Unified router system for Stacksync Workflows CDK.
Handles versioned endpoints, request validation, and response formatting.
"""

import logging
import time
import uuid
import os
import json
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union, TypeVar, Protocol, cast
from pathlib import Path

from flask import Flask, jsonify, request
from pydantic import BaseModel, ValidationError

from .errors import ManagedError
from .request import Request
from .responses import Response


logger = logging.getLogger(__name__)


F = TypeVar('F', bound=Callable[..., Any])


class RouteHandler(Protocol):
    """Protocol for route handlers."""
    methods: List[str]
    category: str
    version: str
    __call__: Callable[..., Any]


def create_route_url(base_path: str, endpoint: str, version: str) -> str:
    """Create a versioned URL for an endpoint."""
    return f"/{base_path.strip('/')}/{endpoint}/{version}"


class ModuleRouter:
    """Router supporting versioned endpoints and module functionality."""
    
    def __init__(
        self,
        app: Optional[Flask] = None,
        base_path: str = "",
        module_id: Optional[str] = None,
        module_config: Optional[Dict[str, Any]] = None,
        routes_dir: str = "routes"
    ):
        """Initialize the router.
        
        Args:
            app: Optional Flask app instance
            base_path: Base path for all routes
            module_id: Optional module identifier
            module_config: Optional module configuration
            routes_dir: Directory containing routes (default: "routes")
        """
        self.app = app or Flask(__name__)
        self.base_path = base_path.strip("/")
        self.module_id = module_id or str(uuid.uuid4())
        self.module_config = module_config or {}
        self.routes_dir = routes_dir
        self.routes: Dict[str, Dict[str, RouteHandler]] = {}
        
        # Setup basic routes
        self._setup_health_check()
        self._setup_module_info()
        self._setup_auto_schema_routes()
    
    def _find_schema_file(self, version: str) -> Optional[str]:
        """Find schema.json file for a given version.
        
        Args:
            version: Version to find schema for
            
        Returns:
            Path to schema file if found, None otherwise
        """
        try:
            # Build path to version directory
            version_dir = Path(self.routes_dir) / self.base_path / version
            schema_file = version_dir / "schema.json"
            
            if schema_file.exists():
                return str(schema_file)
                
            return None
        except Exception as e:
            logger.warning(f"Error finding schema file: {e}")
            return None
    
    def _setup_auto_schema_routes(self) -> None:
        """Set up automatic schema routes for versions without explicit /schema endpoints."""
        try:
            # Get all version directories
            base_dir = Path(self.routes_dir) / self.base_path
            if not base_dir.exists():
                return
                
            for version_dir in base_dir.iterdir():
                if not version_dir.is_dir() or not version_dir.name.startswith("v"):
                    continue
                    
                version = version_dir.name
                
                # Check if /schema route already exists for this version
                if version in self.routes and "schema" in self.routes[version]:
                    continue
                    
                # Look for schema.json
                schema_file = self._find_schema_file(version)
                if not schema_file:
                    continue
                    
                # Create automatic schema route
                url = create_route_url(self.base_path, "schema", version)
                
                @self.app.route(url, methods=["GET"])
                def get_schema(schema_path=schema_file):
                    try:
                        with open(schema_path, 'r') as f:
                            schema_data = json.load(f)
                        return Response.success(
                            data=schema_data,
                            metadata={
                                "version": version,
                                "category": "schema",
                                "auto_generated": True
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error serving schema file {schema_path}: {e}")
                        return Response.error(
                            ManagedError.service_error(
                                service=self.module_config.get("MODULE_NAME", "unknown"),
                                message=f"Error serving schema: {str(e)}",
                                exc_info=e
                            )
                        )
                
                # Register route metadata
                if version not in self.routes:
                    self.routes[version] = {}
                    
                wrapped = cast(RouteHandler, get_schema)
                wrapped.methods = ["GET"]
                wrapped.category = "schema"
                wrapped.version = version
                self.routes[version]["schema"] = wrapped
                
                logger.info(f"Registered automatic schema route for {version} from {schema_file}")
                
        except Exception as e:
            logger.error(f"Error setting up automatic schema routes: {e}")
    
    def _setup_health_check(self) -> None:
        """Set up the health check endpoint."""
        @self.app.route("/health", methods=["GET"])
        def health_check():
            return jsonify({
                "status": "success",
                "message": "Module is healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "module_id": self.module_id,
                "module_version": self.module_config.get("MODULE_VERSION", "unknown")
            })

    
    
    def _setup_module_info(self) -> None:
        """Set up the module info endpoint."""
        @self.app.route("/info", methods=["GET"])
        def module_info():
            return jsonify({
                "status": "success",
                "data": {
                    "id": self.module_id,
                    "name": self.module_config.get("MODULE_NAME", "Unknown Module"),
                    "description": self.module_config.get("MODULE_DESCRIPTION", ""),
                    "version": self.module_config.get("MODULE_VERSION", "unknown"),
                    "author": self.module_config.get("MODULE_AUTHOR", "unknown"),
                    "routes": self._get_registered_routes()
                }
            })
    
    def _get_registered_routes(self) -> Dict[str, Any]:
        """Get information about registered routes."""
        routes = {}
        for version, endpoints in self.routes.items():
            routes[version] = {
                name: {
                    "url": create_route_url(self.base_path, name, version),
                    "methods": handler.methods,
                    "category": handler.category,
                    "description": handler.__doc__ or "No description available"
                }
                for name, handler in endpoints.items()
            }
        return routes
    
    def route(
        self,
        endpoint: str,
        versions: List[str],
        methods: List[str] = ["POST"],
        category: str = "action",
        request_model: Optional[Type[BaseModel]] = None,
        response_model: Optional[Type[BaseModel]] = None
    ) -> Callable[[F], F]:
        """Decorator to register a route with versions.
        
        Args:
            endpoint: Endpoint name (used in URL)
            versions: List of supported versions
            methods: HTTP methods to support
            category: Route category (action/trigger/info)
            request_model: Optional Pydantic model for request validation
            response_model: Optional Pydantic model for response validation
        """
        def decorator(handler: F) -> F:
            for version in versions:
                url = create_route_url(self.base_path, endpoint, version)
                
                @self.app.route(url, methods=methods)
                @wraps(handler)
                def wrapped_handler(*args: Any, **kwargs: Any) -> Any:
                    start_time = time.time()
                    request_id = str(uuid.uuid4())
                    
                    try:
                        # Create request object
                        req = Request()
                        req.version = version
                        req.category = category
                        req.module_id = self.module_id
                        req.request_id = request_id
                        
                        # Validate request data if model provided
                        if request_model and request.is_json:
                            validated_data = request_model(**req.json)
                            req.validated_data = validated_data
                        
                        # Execute handler
                        result = handler(req, *args, **kwargs)
                        
                        # Handle different response types
                        if isinstance(result, (Response, tuple)):
                            return result
                        
                        # Validate response if model provided
                        if response_model:
                            result = response_model(**result).dict()
                        
                        # Create response
                        duration = (time.time() - start_time) * 1000
                        return Response.success(
                            data=result,
                            metadata={
                                "version": version,
                                "category": category,
                                "endpoint": endpoint,
                                "request_id": request_id,
                                "duration_ms": duration
                            }
                        )
                        
                    except ValidationError as e:
                        logger.error(
                            f"Validation error in {endpoint} {version}",
                            extra={
                                "errors": e.errors(),
                                "request_id": request_id,
                                "request_data": request.get_json(silent=True)
                            }
                        )
                        return Response.error(
                            ManagedError.validation_error(
                                message="Invalid request data",
                                data={"errors": e.errors()}
                            )
                        )
                        
                    except Exception as e:
                        logger.exception(
                            f"Error in {endpoint} {version}",
                            extra={
                                "request_id": request_id,
                                "request_data": request.get_json(silent=True)
                            }
                        )
                        return Response.error(
                            ManagedError.service_error(
                                service=self.module_config.get("MODULE_NAME", "unknown"),
                                message=str(e),
                                exc_info=e
                            )
                        )
                
                # Store route metadata
                wrapped = cast(RouteHandler, wrapped_handler)
                wrapped.methods = methods
                wrapped.category = category
                wrapped.version = version
                
                # Register route
                if version not in self.routes:
                    self.routes[version] = {}
                self.routes[version][endpoint] = wrapped
                
                logger.info(
                    f"Registered route: {url} [{', '.join(methods)}] "
                    f"-> {handler.__module__}.{handler.__name__}"
                )
            
            return cast(F, handler)
        
        return decorator
    
    def run(self, host: str = "0.0.0.0", port: int = 2005, **kwargs) -> None:
        """Run the module service.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            **kwargs: Additional arguments passed to Flask run
        """
        self.app.run(host=host, port=port, **kwargs) 