"""
Unified router system for Stacksync Workflows CDK.
Handles versioned endpoints, request validation, and response formatting.
"""

import functools
import inspect
import json
import logging
import sys
import time
import traceback
import uuid
import os
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union, TypeVar, Protocol, cast, get_type_hints
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
    """Create URL for a route."""
    parts = [p for p in [base_path, version, endpoint] if p]
    return f"/{'/'.join(parts)}"


class ModuleRouter:
    """Router supporting versioned endpoints and module functionality."""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """Ensure single router instance per app."""
        if not cls._instance:
            cls._instance = super(ModuleRouter, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
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
        if self._initialized:
            return
            
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
        
        self._initialized = True

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
            # Find all version directories
            module_dir = Path(self.routes_dir) / self.base_path
            if not module_dir.exists():
                return
                
            for version_dir in module_dir.iterdir():
                if not version_dir.is_dir():
                    continue
                    
                version = version_dir.name
                schema_file = version_dir / "schema.json"
                
                if not schema_file.exists():
                    continue
                    
                # Create schema route if not already registered
                if version in self.routes and "schema" in self.routes[version]:
                    continue
                    
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
        versions: Optional[List[str]] = None,
        methods: Optional[List[str]] = None,
        category: str = "action"
    ) -> Callable[[F], F]:
        """Simplified route decorator.
        
        Args:
            endpoint: Endpoint name (used in URL)
            versions: List of supported versions (defaults to ["v1"])
            methods: HTTP methods (defaults to ["POST"])
            category: Route category (defaults to "action")
        """
        versions = versions or ["v1"]
        methods = methods or ["POST"]
        
        def decorator(handler: F) -> F:
            for version in versions:
                url = create_route_url(self.base_path, endpoint, version)
                
                @self.app.route(url, methods=methods)
                @functools.wraps(handler)
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
                        
                        # Execute handler
                        result = handler(req, *args, **kwargs)
                        
                        # Handle different response types
                        if isinstance(result, (Response, tuple)):
                            return result
                        
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
                        
                    except Exception as e:
                        # Get detailed error context
                        exc_type, exc_value, exc_tb = sys.exc_info()
                        tb = traceback.extract_tb(exc_tb)
                        
                        # Get local variables at point of error
                        frame = next(
                            (frame for frame in inspect.trace() if frame.code_context),
                            None
                        )
                        locals_dict = frame.frame.f_locals if frame else {}
                        
                        # Clean locals (remove request object and self)
                        clean_locals = {
                            k: str(v) for k, v in locals_dict.items()
                            if k not in {"self", "req", "request"}
                        }
                        
                        error_context = {
                            "traceback": [str(f) for f in tb],
                            "locals": clean_locals,
                            "function": handler.__name__,
                            "module": handler.__module__,
                            "line": tb[-1].lineno if tb else None,
                            "file": tb[-1].filename if tb else None,
                            "request_id": request_id
                        }
                        
                        if isinstance(e, ManagedError):
                            e.data = {**(e.data or {}), **error_context}
                            return Response.error(e)
                        else:
                            return Response.error(
                                ManagedError.service_error(
                                    service=self.module_config.get("MODULE_NAME", "unknown"),
                                    message=str(e),
                                    data=error_context,
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