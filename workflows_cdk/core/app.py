"""
Flask application factory with automated configuration.
"""

import os
import logging
import traceback
from typing import Any, Dict, List, Optional, Type
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

from .errors import ManagedError
from .responses import Response



def create_app(
    name: str,
    routes_dir: str,
    config: Optional[Dict[str, Any]] = None,
    sentry_dsn: Optional[str] = None,
    cors_origins: Optional[List[str]] = None
) -> Flask:
    """Create a Flask application with standard configuration.
    
    Args:
        name: Application name
        routes_dir: Directory containing route modules
        config: Additional configuration
        sentry_dsn: Sentry DSN for error tracking
        cors_origins: Allowed CORS origins
    """
    # Create Flask app
    app = Flask(name)
    
    # Load configuration
    app.config.update({
        "JSON_SORT_KEYS": False,
        "PROPAGATE_EXCEPTIONS": True,
        **(config or {})
    })
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Configure Sentry
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            environment=os.getenv("ENVIRONMENT", "development"),
            before_send=_prepare_sentry_event
        )
    
    # Configure CORS
    CORS(app, origins=cors_origins or ["*"])
    
    # Register error handlers
    @app.errorhandler(ManagedError)
    def handle_managed_error(error):
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
    def handle_error(error):
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
        event["extra"] = {
            **event.get("extra", {}),
            "traceback": "".join(traceback.format_tb(tb)),
            "locals": _get_locals_from_traceback(tb)
        }
    return event


def _get_locals_from_traceback(tb) -> Dict[str, Any]:
    """Extract local variables from traceback."""
    locals_dict = {}
    while tb:
        if tb.tb_frame.f_locals:
            # Filter out large objects and private variables
            locals_dict.update({
                k: repr(v) for k, v in tb.tb_frame.f_locals.items()
                if not k.startswith("_") and len(repr(v)) < 1000
            })
        tb = tb.tb_next
    return locals_dict


def _register_routes(app: Flask, routes_dir: str) -> None:
    """Auto-register all routes in the specified directory."""
    import importlib
    import pkgutil
    import inspect
    from .decorators import module_route
    
    # Import all modules in routes directory
    package = importlib.import_module(routes_dir)
    
    # Track registered routes by version
    routes_by_version = {}
    
    # Scan for routes
    for _, name, _ in pkgutil.iter_modules(package.__path__):
        if name.startswith("v"):
            version = name
            module = importlib.import_module(f"{routes_dir}.{name}")
            
            # Find all functions decorated with module_route
            for item_name, item in inspect.getmembers(module):
                if (
                    inspect.isfunction(item) and 
                    hasattr(item, "methods") and 
                    hasattr(item, "category")
                ):
                    # Register route based on category
                    if item.category == "action":
                        route = f"/actions/{version}"
                    elif item.category == "info":
                        route = f"/schema/{version}"
                    else:
                        route = f"/{item.category}/{version}"
                    
                    # Add route
                    app.add_url_rule(
                        route,
                        f"{item_name}_{version}",
                        item,
                        methods=item.methods
                    )
                    app.logger.info(
                        f"Registered route: {route} [{', '.join(item.methods)}] "
                        f"-> {item.__module__}.{item.__name__}"
                    ) 