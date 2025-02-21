"""
Dynamic routing implementation for Flask applications.
Automatically discovers and registers routes based on your file system structure.
"""
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union, cast
from flask import Flask, request as flask_request, current_app
from flask_cors import CORS
import inspect
import os
import sys
import types
import importlib.util
import logging
import yaml
from pathlib import Path
from sentry_sdk.integrations.flask import FlaskIntegration
from .errors import ManagedError
from .responses import Response
from .sentry import init_sentry
from .validation import validate_request
import sentry_sdk
import traceback



def load_app_config(app_dir: str) -> Dict[str, Any]:
    """Load application configuration from app_config.yaml."""
    config_path = os.path.join(app_dir, "app_config.yaml")
    if not os.path.exists(config_path):
        return {}
        
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}

def log_error_details(app: Flask, error: Union[ManagedError, Exception], is_managed: bool = False) -> Optional[str]:
    """Centralized error logging function."""
    # Get full traceback from current exception context
    exc_info = sys.exc_info()
    if exc_info[0] is None:  # If no current exception context, create one from the error
        exc_info = (type(error), error, error.__traceback__)
    
    tb_string = ''.join(traceback.format_exception(*exc_info))
    
    # Log the full traceback
    app.logger.error("\nTraceback:")
    app.logger.error(tb_string)
    
    # Capture exception with full context
    print(f"Error: {error}", )
    try:
        sentry_sdk.capture_exception(error)
    except Exception as e:
        print(f"Error capturing exception: {e}")
    
    return tb_string

def wrap_route_handler(handler: Callable) -> Callable:
    """Wrap route handler with error handling and request context."""
    @wraps(handler)
    def wrapped_handler(*args: Any, **kwargs: Any) -> Any:
        try:
            # Get required fields from route info if it exists
            required_fields = getattr(handler, "__route_info__", {}).get("required_fields", [])
            
            # Execute handler and get response
            validate_request(flask_request, required_fields)
            response = handler(*args, **kwargs)
            
            # If response is a dict, convert to JSON response
            if isinstance(response, dict):
                return Response.success(data=response)
            return response
        except ManagedError as managed_error:
            # Log error details and let it propagate to the error handler
            log_error_details(current_app, managed_error, is_managed=True)
            raise
        except Exception as unhandled_error:
            # Log error details and let it propagate to the error handler
            log_error_details(current_app, unhandled_error)
            raise

    return wrapped_handler

class Router:
    """Flask File System Router that enables automatic route path detection based on file location."""
    
    def __init__(self, app: Optional[Flask] = None, *, 
                 config: Optional[Dict[str, Any]] = None,
                 sentry_dsn: Optional[str] = None,
                 cors_origins: Optional[List[str]] = None) -> None:
        """Initialize router with storage for routes.
        
        Args:
            app: Optional Flask application instance
            config: Optional configuration dictionary
            sentry_dsn: Optional Sentry DSN for error tracking
            cors_origins: Optional list of allowed CORS origins
        """

        # List to store all discovered routes
        self.routes: List[Dict[str, Any]] = []
        # Flask application instance
        self.app: Optional[Flask] = None
        self._router_instance = self
        self.environment = os.getenv("ENVIRONMENT", "dev")

        # Load configuration from app_config.yaml
        self.app_config = load_app_config(os.getcwd())
        self.app_settings = self.app_config.get("app_settings", {})
        # Store configuration with proper null checks
        self.config = config or {}
        self.sentry_dsn = sentry_dsn or self.app_settings.get("sentry_dsn")
        self.cors_origins = cors_origins

        if app is not None:
            self.init_app(app)

    def run_app(self, app: Flask) -> None:
        """Run the app."""
        # Enable debug mode
        app.debug = True
        # Run with output unbuffered
        port = self.app_settings.get("port")
        logger = logging.getLogger(__name__)
        debug_mode = self.app_settings.get("debug",True)

        app.run(host="0.0.0.0", port=port or 2001, debug=debug_mode, use_reloader=debug_mode, use_debugger=debug_mode)


    def configure_logging(self, app: Flask) -> None:
        """Configure application logging."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(levelname)s - %(message)s'
        )

    def configure_sentry(self, app: Flask) -> None:
        """Configure Sentry error tracking."""
        dsn = self.config.get("sentry_dsn") or self.app_settings.get("sentry_dsn")
        init_sentry(app, dsn)

    def configure_cors(self, app: Flask) -> None:
        """Configure CORS settings."""
        origins = self.cors_origins or self.app_settings.get("cors_origins")
        if origins:
            CORS(app, origins=origins)

    def _create_route_info(self, function: Callable, rule: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create route information dictionary from a function and options.
        
        Args:
            function: The route handler function
            rule: Optional URL rule
            options: Optional route options
            
        Returns:
            Dictionary containing route information
            
        Raises:
            ValueError: If module path cannot be determined
        """
        options = options or {}
        # Get the file path of the module containing this function
        function_module = inspect.getmodule(function)
        if not function_module or not function_module.__file__:
            raise ValueError("Could not determine the module path for the function")
            
        # Get base path from the file's location
        directory_name = self.app_settings.get("routes_directory", "routes")
        routes_directory = Path(os.path.join(os.getcwd(), directory_name))
        module_file_path = Path(function_module.__file__).resolve()
        
        # Check if the module is in the routes directory
        try:
            relative_path = module_file_path.relative_to(routes_directory)
            # Generate base path from routes directory structure
            path_parts = list(relative_path.parent.parts)
            base_path = "/" + "/".join(path_parts)
        except ValueError:
            # Module is not in routes directory, use provided rule as is
            base_path = ""
            path_parts = []
            
        # Generate the full URL path
        if rule:
            endpoint_path = rule if rule.startswith("/") else f"/{rule}"
        else:
            endpoint_path = f"/{function.__name__}"
            
        full_url_path = f"{base_path}{endpoint_path}"
         
        # Set default HTTP methods to POST if not specified
        http_methods = options.get("methods", ["POST"])
        
        # Generate unique endpoint name
        endpoint_name = f"{'.'.join(path_parts)}.{function.__name__}" if path_parts else function.__name__

        # Wrap the function with error handling and response formatting
        wrapped_function = wrap_route_handler(function)
        # Create route information dictionary
        route_info = {
            "path": full_url_path,
            "endpoint": endpoint_name,
            "view_func": wrapped_function,
            "methods": http_methods
        }
        # Add any additional options
        for key, value in options.items():
            if key != "methods":  # Skip methods as we've already handled it
                route_info[key] = value
                
        return route_info
            
    def discover_routes(self) -> None:
        """
        Automatically discover and register all routes in the routes directory.
        This method scans your project's routes folder and registers each endpoint it finds.
        """
        # Get the directory where your application is running
        current_working_directory = os.getcwd()
        
        # Get routes directory from config or use default
        routes_dir = self.app_settings.get("routes_directory", "routes") if self.app_settings.get("routes_directory") else "routes"
        
        # Construct the full path to your routes directory
        routes_directory = Path(os.path.join(current_working_directory, routes_dir))
        if not routes_directory.exists():
            print(f"Routes directory not found at: {routes_directory}")
            return

        # Add the project root to Python path so it can find your modules
        if current_working_directory not in sys.path:
            sys.path.insert(0, current_working_directory)

        # Store the original router instance (if it exists)
        original_router_module = sys.modules.get('main', None)
        
        # Create a temporary main module with our router instance
        temporary_main_module = types.ModuleType('main')
        setattr(temporary_main_module, 'router', self)
        setattr(temporary_main_module, '__file__', os.path.join(current_working_directory, 'main.py'))
        sys.modules['main'] = temporary_main_module

        try:
            # Find all Python files in routes directory and its subdirectories
            for route_file_path in routes_directory.rglob("*.py"):
                # Skip __init__.py files
                if route_file_path.name == "__init__.py":
                    continue
                    
                try:
                    # Convert file path to a Python module path (e.g., routes.users.v1.route)
                    relative_path = route_file_path.relative_to(current_working_directory)
                    module_name = str(relative_path.with_suffix("")).replace(os.sep, ".")
                    
                    # Create a module specification for importing
                    module_spec = importlib.util.spec_from_file_location(module_name, str(route_file_path))
                    if module_spec is None or module_spec.loader is None:
                        continue
                        
                    # Create the module and set up its environment
                    route_module = importlib.util.module_from_spec(module_spec)
                    sys.modules[module_name] = route_module
                    
                    # Add the route file's parent directory to path for relative imports
                    route_parent_directory = str(route_file_path.parent)
                    if route_parent_directory not in sys.path:
                        sys.path.insert(0, route_parent_directory)
                        
                    # Execute the module to process its contents
                    module_spec.loader.exec_module(route_module)
                    
                    # Find all functions that have been decorated with our route decorator
                    for function_name, function_object in inspect.getmembers(route_module):
                        if inspect.isfunction(function_object):
                            # Check if this function has route information attached
                            if hasattr(function_object, "__route_info__"):
                                route_info = getattr(function_object, "__route_info__")
                                if route_info not in self.routes:
                                    self.routes.append(route_info)
                    
                    # Clean up by removing the temporary path addition
                    if route_parent_directory in sys.path:
                        sys.path.remove(route_parent_directory)
                    
                except Exception as error:
                    print(f"Error while processing route file {route_file_path}: {error}")
                    
        finally:
            # Restore the original state
            if original_router_module is not None:
                sys.modules['main'] = original_router_module
            else:
                sys.modules.pop('main', None)
            
            # Remove the project root from sys.path
            if current_working_directory in sys.path:
                sys.path.remove(current_working_directory)
    
    def register_error_handlers(self, app: Flask) -> None:
        """Register error handlers for the application."""
        
        @app.errorhandler(ManagedError)
        def handle_managed_error(error: ManagedError):
            return Response.error(error)

        @app.errorhandler(Exception)
        def handle_unhandled_error(error: Exception):
            return Response.error(error, status_code=500)

    def _register_core_routes(self, app: Flask) -> None:
        """Register core routes."""
        @app.route("/health", methods=["GET"])
        def health_check():
            return Response.success(data={"status": "healthy"})
        
        @app.route("/app_info", methods=["GET"])
        def module_info():
           return Response.success(data={
               "name": self.app_config.get("app_name"),
               "version": self.app_config.get("app_version"),
               "description": self.app_config.get("app_description"),
               "routes": self.routes
           })
        
        @app.route("/routes", methods=["GET"])
        def routes():
            return Response.success(data={
                "routes": self.routes
            })
            
    def init_app(self, app: Flask) -> None:
        """Initialize the router with a Flask app and register all discovered routes."""
        self.app = app
        # Update Flask configuration
        self.configure_sentry(app)
        app.config.update({
            "JSON_SORT_KEYS": False,
            "PROPAGATE_EXCEPTIONS": True,
            **self.config,
            **self.app_settings
        })

        # Configure components
        self.configure_logging(app)
        self.configure_cors(app)

        
        # First discover all routes in the project
        self.discover_routes()

        # Register error handlers
        self.register_error_handlers(app)
        
        # Register each discovered route with Flask
        for route_info in self.routes:
            app.add_url_rule(
                route_info["path"],
                endpoint=route_info["endpoint"],
                view_func=route_info["view_func"],
                methods=route_info["methods"],
                **{k: v for k, v in route_info.items() if k not in ["path", "endpoint", "view_func", "methods"]}
            )
            print(f"Registered route: {route_info['path']} with methods {route_info['methods']}") if self.environment == "dev" or self.environment == "development" else None

        # Register core routes
        self._register_core_routes(app)


    def route(self, rule: Optional[str] = None, **options: Any) -> Callable:
        """
        Route decorator that combines base path with endpoint path.
        
        Examples:
        
        1. Simple route with parameter:
            @router.route("/users/<user_id>")
            def get_user(user_id):
                return f"User {user_id}"
                
        2. Route with type-specific parameter:
            @router.route("/users/<int:user_id>/posts/<int:post_id>")
            def get_user_post(user_id, post_id):
                return f"User {user_id}, Post {post_id}"
                
        3. Route with multiple parameters:
            @router.route("/org/<org_id>/users/<user_id>/teams/<team_id>")
            def get_org_user_team(org_id, user_id, team_id):
                return f"Org {org_id}, User {user_id}, Team {team_id}"
        """

        def decorator(function: Callable) -> Callable:
            try:
                # Create route information using helper method
                route_info = self._create_route_info(function, rule, options)
                
                # Store route info on the function for later discovery
                setattr(function, "__route_info__", route_info)
                
                # Store route for registration if not already stored
                if route_info not in self.routes:
                    self.routes.append(route_info)
          
                # If Flask app is already initialized, register the route immediately
                if self.app:
                    self.app.add_url_rule(
                        route_info["path"],
                        endpoint=route_info["endpoint"],
                        view_func=route_info["view_func"],
                        methods=route_info["methods"],
                        **{k: v for k, v in route_info.items() if k not in ["path", "endpoint", "view_func", "methods"]}
                    )
                
            except Exception as error:
                print(f"Error registering route for {function.__name__}: {error}")
                raise
                
            @wraps(function)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return function(*args, **kwargs)
            return wrapper
        return decorator

