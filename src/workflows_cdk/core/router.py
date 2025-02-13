"""
Router implementation for Workflows CDK.
"""

from typing import Any, Callable, Dict, List, Optional, TypeVar, cast, TYPE_CHECKING
from functools import wraps
import inspect
import os
from pathlib import Path
from flask import Flask as BaseFlask, jsonify, current_app

F = TypeVar('F', bound=Callable[..., Any])

if TYPE_CHECKING:
    class Flask(BaseFlask):
        router: 'ModuleRouter'
else:
    Flask = BaseFlask

class ModuleRouter:
    """Router supporting versioned endpoints and module functionality."""
    
    def __init__(self, app: Flask) -> None:
        """Initialize router with Flask app instance."""
        self.app = app
        self.routes: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._setup_core_routes()

    def _setup_core_routes(self) -> None:
        """Setup core application routes."""
        @self.app.route("/health", methods=["GET"])
        def health_check():
            """Health check endpoint."""
            return jsonify({
                "status": "healthy",
                "version": os.getenv("VERSION", "unknown")
            })

        @self.app.route("/info", methods=["GET"])
        def module_info():
            """Module information endpoint."""
            return jsonify({
                "name": self.app.name,
                "description": "Module information",
                "routes": self.routes
            })

    def route(
        self,
        endpoint: Optional[str] = None,
        methods: Optional[List[str]] = None,
        category: str = "action"
    ) -> Callable[[F], F]:
        """Route decorator that automatically detects module and version from file path."""

        def decorator(handler: F) -> F:
            # Get the module path from the handler's module
            module = inspect.getmodule(handler)
            if module is None or not hasattr(module, "__file__") or module.__file__ is None:
                raise ValueError("Could not determine module path")
                
            module_path = Path(module.__file__)
            
            # Extract module name and version from path
            module_name = module_path.parent.parent.name
            version = module_path.parent.name
            
            # Use function name if endpoint not specified
            endpoint_name = endpoint or handler.__name__
            
            # Default to POST if no methods specified
            route_methods = methods or ["POST"]
            
            # Construct route path
            route_path = f"/{module_name}/{version}/{endpoint_name}"
            
            # Store route information
            if module_name not in self.routes:
                self.routes[module_name] = {}
            if version not in self.routes[module_name]:
                self.routes[module_name][version] = {}
                
            self.routes[module_name][version][endpoint_name] = {
                "methods": route_methods,
                "category": category,
                "path": route_path,
                "doc": handler.__doc__
            }
            
            # Register route with Flask
            self.app.add_url_rule(
                route_path,
                f"{module_name}_{version}_{endpoint_name}",
                handler,
                methods=route_methods
            )
            
            return handler
            
        return decorator

# Global router instance
_router: Optional[ModuleRouter] = None

def init_app(app: Flask) -> ModuleRouter:
    """Initialize router with Flask app."""
    global _router
    if _router is None:
        _router = ModuleRouter(app)
        setattr(app, 'router', _router)
    return _router

def get_router() -> ModuleRouter:
    """Get the current router instance."""
    if _router is None:
        raise RuntimeError("Router not initialized. Call init_app first.")
    return _router 