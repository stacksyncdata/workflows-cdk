"""
Flask application factory with automated configuration.
"""

import os
import logging
from typing import Any, Dict, List, Optional
import yaml 

from flask import Flask
from flask_cors import CORS
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

from .errors import ManagedError
from .responses import Response
from . import router

def load_app_config(app_dir: str) -> Dict[str, Any]:
    """Load application configuration from app_config.yaml."""
    config_path = os.path.join(app_dir, "app_config.yaml")
    if not os.path.exists(config_path):
        return {}
        
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}

def create_app(
    name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    sentry_dsn: Optional[str] = None,
    cors_origins: Optional[List[str]] = None
) -> Flask:
    """Create a Flask application with standard configuration."""
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
        format='%(levelname)s - %(message)s'
    )
    
    # Configure Sentry
    dsn = sentry_dsn or app_settings.get("sentry_dsn")
    if dsn and isinstance(dsn, str) and dsn.startswith(("http://", "https://")):
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            environment=os.getenv("ENVIRONMENT", "development")
        )
    else:
        app.logger.info("Sentry disabled - no valid DSN")
    
    # Configure CORS
    if cors_origins:
        CORS(app, origins=cors_origins)
    
    # Register error handlers
    @app.errorhandler(ManagedError)
    def handle_managed_error(error: ManagedError):
        app.logger.error(f"Managed error: {error.error}")
        return Response.error(error)
    
    @app.errorhandler(Exception)
    def handle_error(error: Exception):
        app.logger.error(f"Unhandled error: {str(error)}")
        sentry_sdk.capture_exception(error)
        return Response.error(error, status_code=500)
    
    # Initialize router
    router.init_app(app)
    
    return app 