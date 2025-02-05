"""
Unified router system for Stacksync Workflows CDK.
Handles versioned endpoints, request validation, and response formatting.
"""

import logging
import time
import uuid
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union

from flask import Flask, jsonify, request
from pydantic import BaseModel, ValidationError

from .errors import ManagedError
from .request import Request
from .responses import Response


logger = logging.getLogger(__name__)


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
        module_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize the router.
        
        Args:
            app: Optional Flask app instance
            base_path: Base path for all routes
            module_id: Optional module identifier
            module_config: Optional module configuration
        """
        self.app = app or Flask(__name__)
        self.base_path = base_path.strip("/")
        self.module_id = module_id or str(uuid.uuid4())
        self.module_config = module_config or {}
        self.routes: Dict[str, Dict[str, Callable]] = {}
        
        # Setup basic routes
        self._setup_health_check()
        self._setup_module_info()
    
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
                    "methods": getattr(handler, "methods", ["GET"]),
                    "category": getattr(handler, "category", "unknown"),
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
    ) -> Callable:
        """Decorator to register a route with versions.
        
        Args:
            endpoint: Endpoint name (used in URL)
            versions: List of supported versions
            methods: HTTP methods to support
            category: Route category (action/trigger/info)
            request_model: Optional Pydantic model for request validation
            response_model: Optional Pydantic model for response validation
        """
        def decorator(handler: Callable) -> Callable:
            for version in versions:
                url = create_route_url(self.base_path, endpoint, version)
                
                @self.app.route(url, methods=methods)
                @wraps(handler)
                def wrapped_handler(*args, **kwargs):
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
                wrapped_handler.methods = methods
                wrapped_handler.category = category
                wrapped_handler.version = version
                
                # Register route
                if version not in self.routes:
                    self.routes[version] = {}
                self.routes[version][endpoint] = wrapped_handler
                
                logger.info(
                    f"Registered route: {url} [{', '.join(methods)}] "
                    f"-> {handler.__module__}.{handler.__name__}"
                )
            
            return handler
        
        return decorator
    
    def run(self, host: str = "0.0.0.0", port: int = 5000, **kwargs) -> None:
        """Run the module service.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            **kwargs: Additional arguments passed to Flask run
        """
        self.app.run(host=host, port=port, **kwargs) 