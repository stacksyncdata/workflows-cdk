"""
Flask application factory with automated configuration.
"""

import os
import logging
import traceback
import importlib
import pkgutil
import inspect
from typing import Any, Dict, List, Optional, cast
from pathlib import Path

from flask import Flask, jsonify, request, Blueprint
from flask_cors import CORS
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
import yaml  # type: ignore

from .errors import ManagedError
from .responses import Response
from .router import ModuleRouter


def load_app_config(app_dir: str) -> Dict[str, Any]:
    """Load application configuration from app_config.yaml."""
    config_path = os.path.join(app_dir, "app_config.yaml")
    if not os.path.exists(config_path):
        return {}
        
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}


def create_app(
    name: Optional[str] = None,
    routes_dir: str = "routes",
    config: Optional[Dict[str, Any]] = None,
    sentry_dsn: Optional[str] = None,
    cors_origins: Optional[List[str]] = None
) -> Flask:
    """Create a Flask application with standard configuration.
    
    Args:
        name: Application name (optional, will be loaded from app_config.yaml if not provided)
        routes_dir: Directory containing route modules
        config: Additional configuration
        sentry_dsn: Sentry DSN for error tracking
        cors_origins: Allowed CORS origins
    """
    # Load configuration from app_config.yaml
    app_config = load_app_config(os.getcwd())
    app_settings = app_config.get("app_settings", {})
    
    # Create Flask app using name from config or parameter
    app = Flask(name or app_settings.get("app_name", "workflows-module"))
    
    # Load configuration
    app.config.update({
        "JSON_SORT_KEYS": False,
        "PROPAGATE_EXCEPTIONS": True,
        **(config or {}),
        **app_settings
    })
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Configure Sentry
    if sentry_dsn or app_settings.get("sentry_dsn"):
        sentry_sdk.init(
            dsn=sentry_dsn or app_settings.get("sentry_dsn"),
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            environment=os.getenv("ENVIRONMENT", "development"),
            before_send=_prepare_sentry_event
        )
    
    # Configure CORS
    if cors_origins:
        CORS(app, origins=cors_origins)
    
    # Register error handlers
    @app.errorhandler(ManagedError)
    def handle_managed_error(error: ManagedError):
        # Log error details
        app.logger.error(
            f"Managed error in {request.endpoint}",
            extra={
                "error": str(error),
                "data": error.data,
                "metadata": error.metadata,
                "traceback": traceback.format_exc(),
                "request": {
                    "method": request.method,
                    "url": request.url,
                    "headers": dict(request.headers),
                    "data": request.get_json(silent=True)
                }
            }
        )
        return Response.error(error)
    
    @app.errorhandler(Exception)
    def handle_error(error: Exception):
        # Log unexpected error
        app.logger.error(
            f"Unexpected error in {request.endpoint}",
            extra={
                "error": str(error),
                "traceback": traceback.format_exc(),
                "request": {
                    "method": request.method,
                    "url": request.url,
                    "headers": dict(request.headers),
                    "data": request.get_json(silent=True)
                }
            }
        )
        sentry_sdk.capture_exception(error)
        return Response.error(error, status_code=500)
    
    # Auto-register routes
    _register_routes(app, routes_dir)
    
    return app


def _prepare_sentry_event(event: Dict[str, Any], hint: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare event data for Sentry."""
    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]
        if isinstance(exc_value, ManagedError):
            event["extra"] = {
                **event.get("extra", {}),
                "error_data": exc_value.data,
                "error_metadata": exc_value.metadata
            }
    return event


def _register_routes(app: Flask, routes_dir: str) -> None:
    """Register routes from directory structure.
    
    Directory structure:
    routes/
      module_name/
        v1/
          route.py
          schema.json  # Optional schema file
        v2/
          route.py
          schema.json  # Optional schema file
    """
    try:
        routes_path = Path(routes_dir)
        if not routes_path.exists():
            app.logger.warning(f"Routes directory not found: {routes_dir}")
            return
            
        # Scan for module directories
        for module_dir in routes_path.iterdir():
            if not module_dir.is_dir():
                continue
                
            # Create router for this module
            router = ModuleRouter(
                app=app,
                base_path=module_dir.name,
                module_id=module_dir.name,
                routes_dir=routes_dir  # Pass routes_dir to ModuleRouter
            )
            
            # Scan for version directories
            for version_dir in module_dir.iterdir():
                if not version_dir.is_dir() or not version_dir.name.startswith("v"):
                    continue
                    
                # Import route module
                route_file = version_dir / "route.py"
                if not route_file.exists():
                    continue
                    
                try:
                    module_path = f"{routes_dir}.{module_dir.name}.{version_dir.name}.route"
                    route_module = importlib.import_module(module_path)
                    
                    # Register routes from module
                    for item_name, item in inspect.getmembers(route_module):
                        if inspect.isfunction(item) and hasattr(item, "route"):
                            # Route is already registered by module_route decorator
                            app.logger.info(
                                f"Found route in {module_path}: {item_name}"
                            )
                            
                except Exception as e:
                    app.logger.error(
                        f"Error loading route module {route_file}: {e}",
                        exc_info=True
                    )
                    
    except Exception as e:
        app.logger.error(f"Error registering routes: {e}", exc_info=True) 