"""
Dynamic routing implementation for Flask applications.
Automatically discovers and registers routes based on your file system structure.
"""
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union, cast
from flask import Flask, request as flask_request, current_app, Response as FlaskResponse
from flask_cors import CORS
import inspect
import os
import sys
import types
import importlib.util
import logging
import yaml
import json
from pathlib import Path
from sentry_sdk.integrations.flask import FlaskIntegration
from .errors import ManagedError
from .responses import Response
from .sentry import init_sentry
from .validation import validate_request
from .module_metadata import generate_module_metadata
from .get_environment import get_environment
import sentry_sdk
import traceback



def load_app_config(app_dir: str) -> Dict[str, Any]:
    """Load application configuration from app_config.yaml."""
    config_path = os.path.join(app_dir, "app_config.yaml")
    if not os.path.exists(config_path):
        return {}
        
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}

def load_schema_file(schema_path: str) -> Optional[Dict[str, Any]]:
    """Load and validate a schema file.
    
    Args:
        schema_path: Path to the schema file
        
    Returns:
        Optional[Dict[str, Any]]: The loaded schema or None if invalid/not found
    """
    try:
        if not os.path.exists(schema_path):
            return None
            
        with open(schema_path, 'r') as f:
            schema_data = json.load(f)
            
        # Basic schema validation - ensure it's a dict with required fields
        if not isinstance(schema_data, dict):
            logging.warning(f"Schema file {schema_path} does not contain a valid JSON object")
            return None
            
        return schema_data
    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse schema file {schema_path}: {e}")
        return None
    except Exception as e:
        logging.warning(f"Error loading schema file {schema_path}: {e}")
        return None

def find_schema_files(directory: str) -> Dict[str, Dict[str, Any]]:
    """Find and load all schema.json files in a directory tree.
    
    Args:
        directory: Root directory to search from
        
    Returns:
        Dict[str, Dict[str, Any]]: Map of route paths to their schema data
    """
    schema_files = {}
    try:
        for root, _, files in os.walk(directory):
            if 'schema.json' in files:
                # Load the schema file
                schema_path = os.path.join(root, 'schema.json')
                schema_data = load_schema_file(schema_path)
                
                if schema_data:
                    # Calculate the route path based on directory structure
                    rel_path = os.path.relpath(root, directory)
                    route_path = '/' + rel_path.replace(os.sep, '/')
                    if route_path == '/.':  # Handle root directory case
                        route_path = ''
                    schema_files[route_path] = schema_data
                    
    except Exception as e:
        logging.error(f"Error scanning for schema files: {e}")
        
    return schema_files

def create_schema_handler(schema_data: Dict[str, Any]) -> Callable[[], FlaskResponse]:
    """Create a handler function for a schema route.
    
    Args:
        schema_data: The schema data to return
        
    Returns:
        Callable[[], FlaskResponse]: Handler function for the route
    """
    def schema_handler() -> FlaskResponse:
        return Response(data={"schema": schema_data})
    return schema_handler

def is_production_environment(self) -> bool:
    """Check if current environment is production.
    
    Returns:
        bool: True if environment is production, False otherwise
    """
 
    return get_environment() in ["prod", "production"]

def print_error(message: str) -> None:
    """Log error messages in non-production environments only.
    
    Args:
        message: The error message to log
    """
    if not is_production_environment():
        print(message)

def log_error_details(app: Flask, error: Union[ManagedError, Exception], is_managed: bool = False) -> Optional[str]:
    """Centralized error logging function."""
    # Get full traceback from current exception context
    try:
        sentry_sdk.capture_exception(error)
    except Exception as e:
        print_error(f"Error capturing exception in Sentry: {e}")
    
    
    # Only log errors in non-production environments
    if not is_production_environment():
        exc_info = sys.exc_info()
        if exc_info[0] is None:  # If no current exception context, create one from the error
            exc_info = (type(error), error, error.__traceback__)
        
        tb_string = ''.join(traceback.format_exception(*exc_info))
        # Log the full traceback
        app.logger.error("\nTraceback:")
        app.logger.error(tb_string)
        print_error(f"Error: {error}")
    
    # Always capture exception with Sentry regardless of environment
   
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
        except ValueError as validation_error:
            # Log validation error details with specific context
            log_error_details(current_app, validation_error, is_managed=False)
            # Re-raise as ManagedError to ensure consistent error handling
            raise ManagedError(
                error=validation_error,
                metadata={
                    "type": "validation_error",
                    "original_error": str(validation_error)
                },
                status_code=400
            ) from validation_error
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
        # List to store module metadata
        self.modules_list: List[Dict[str, Any]] = []
        # Flask application instance
        self.app: Optional[Flask] = None
        self._router_instance = self
        self.environment = get_environment()
        self.app_config = load_app_config(os.getcwd())


        self.app_settings = self.app_config.get("app_settings", {})
        self.local_development_settings = self.app_config.get("local_development_settings", {})
        self.port = self.local_development_settings.get("port") or 2002
        self.debug = self.local_development_settings.get("debug",True)


        routes_directory_possible_key_names = ["routes_directory_path", "routes_directory", "routes_dir", "routes_path",]
        # Get routes directory from config using all possible key names or use default
        routes_directory = next(
            (self.app_settings[key] for key in routes_directory_possible_key_names if key in self.app_settings),
            "src/routes"
        )

        self.routes_directory = routes_directory

        self.app_type = self.app_settings.get("app_type", "unknown_app")

        self.config = config or {}
        self.sentry_dsn = sentry_dsn or self.app_settings.get("sentry_dsn") or self.local_development_settings.get("sentry_dsn")
        self.cors_origins = cors_origins or self.local_development_settings.get("cors_origins") or ["*"]

        if app is not None:
            self.init_app(app)

    def run_app(self, app: Flask) -> None:
        """Run the app."""
        # Enable debug mode
        app.debug = True
        # Run with output unbuffered
        port = self.port
        logger = logging.getLogger(__name__)
        debug_mode = self.debug

        app.run(host="0.0.0.0", port=port, debug=debug_mode, use_reloader=debug_mode, use_debugger=debug_mode)


    def configure_logging(self, app: Flask) -> None:
        """Configure application logging."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(levelname)s - %(message)s'
        )

    def configure_sentry(self, app: Flask) -> None:
        """Configure Sentry error tracking."""
        dsn = self.sentry_dsn
        init_sentry(app, dsn)

    def configure_cors(self, app: Flask) -> None:
        """Configure CORS settings."""
        origins = self.cors_origins
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
        function_module = inspect.getmodule(function)
        if not function_module or not function_module.__file__:
            raise ValueError("Could not determine the module path for the function")
            

        routes_directory = Path(os.path.join(os.getcwd(), self.routes_directory))
        module_file_path = Path(function_module.__file__).resolve()
        
        # Check if the module is in the routes directory and generate metadata
        try:
            relative_path = module_file_path.relative_to(routes_directory)
            # Generate base path from routes directory structure
            path_parts = list(relative_path.parent.parts)
            base_path = "/" + "/".join(path_parts)

            # --- Module Metadata Generation ---
            module_dir_rel_str = str(relative_path.parent) # Path relative to routes_directory
            routes_dir_abs_str = str(routes_directory.resolve())
            module_metadata = generate_module_metadata(
                module_dir_rel_str, routes_dir_abs_str, self.app_type
            )
            if module_metadata:
                # Add metadata if not already present (check by module_id)
                if not any(m["module_id"] == module_metadata["module_id"] for m in self.modules_list):
                    self.modules_list.append(module_metadata)
            # --- End Module Metadata Generation ---

        except ValueError:
            # Module is not in routes directory, likely a core or manually placed route.
            # Use provided rule as is, no automatic metadata generation.
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
            
  
        
    def _scan_routes_directory(self) -> list:
        """Scan the routes directory and return route file paths.
        
        Returns:
            list: List of route file paths (Path objects)
        """
        current_working_directory = os.getcwd()
        routes_directory = Path(os.path.join(current_working_directory, self.routes_directory))
        
        if not routes_directory.exists():
            print_error(f"Routes directory not found at: {routes_directory}")
            return []
            
        # Find all Python files in routes directory and its subdirectories
        route_files = [
            path for path in routes_directory.rglob("*.py") 
            if path.name != "__init__.py"
        ]
        
        return route_files
        
    def _collect_route_information(self) -> tuple:
        """Collect information about routes and modules without importing modules.
        
        Returns:
            tuple: (routes_info, modules_list) containing metadata
        """
        current_working_directory = os.getcwd()
        routes_directory = Path(os.path.join(current_working_directory, self.routes_directory))
        
        # Lists to store collected data
        routes_info = []
        modules_list = []
        
        # Get all route files
        route_files = self._scan_routes_directory()
        if not route_files:
            return routes_info, modules_list
        
        # Process each route file path to extract information
        for route_file_path in route_files:
            try:
                # Convert file path to a module path
                relative_path = route_file_path.relative_to(current_working_directory)
                module_name = str(relative_path.with_suffix("")).replace(os.sep, ".")

                # Get route path from directory structure
                rel_to_routes_dir = route_file_path.parent.relative_to(routes_directory)
                route_path = "/" + str(rel_to_routes_dir).replace(os.sep, "/")
                if route_path == "/.":
                    route_path = "/"
                
                # Add route info without importing
                route_info = {
                    "path": route_path,
                    "file": str(route_file_path),
                    "module": module_name,
                    "route_file_path": route_file_path  # Keep the original Path object for discover_routes
                }
                routes_info.append(route_info)
                
                # Generate module metadata
                module_dir_rel_str = str(relative_path.parent.relative_to(self.routes_directory)) if str(relative_path.parent) != self.routes_directory else ""
                routes_dir_abs_str = str(routes_directory.resolve())
                
                module_metadata = generate_module_metadata(
                    module_dir_rel_str, routes_dir_abs_str, self.app_type
                )
                
                if module_metadata and not any(m.get("module_id") == module_metadata["module_id"] for m in modules_list):
                    modules_list.append(module_metadata)
                    
            except Exception as e:
                print_error(f"Error collecting info for route file {route_file_path}: {e}")
        
        return routes_info, modules_list

    def discover_routes(self) -> None:
        """
        Automatically discover and register all routes in the routes directory.
        This method scans your project's routes folder and registers each endpoint it finds.
        """
        current_working_directory = os.getcwd()
        
        # First collect route information without importing
        routes_info, module_list = self._collect_route_information()
        
        # Add collected modules to the module list
        for module in module_list:
            if not any(m.get("module_id") == module["module_id"] for m in self.modules_list):
                self.modules_list.append(module)
        
        if not routes_info:
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
            # Process each route file to import modules and register routes
            for route_info in routes_info:
                try:
                    route_file_path = route_info["route_file_path"]
                    module_name = route_info["module"]
                    
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
                    print_error(f"Error while processing route file {route_file_path}: {error}")
                    
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

    def _get_serializable_routes(self) -> list:
        """Create a JSON-serializable version of the routes list."""
        serializable_routes = []
        
        for route in self.routes:
            serializable_route = {
                "path": route.get("path", ""),
                "endpoint": route.get("endpoint", ""),
                "methods": route.get("methods", ["GET"]),
            }
            serializable_routes.append(serializable_route)
        return serializable_routes

    def _register_core_routes(self, app: Flask) -> None:
        """Register core routes."""
        @app.route("/health", methods=["GET"])
        def health_check():
            return Response.success(data={"status": "healthy"})
        
        @app.route("/app-config", methods=["GET"])
        def app_config():
            try:
                # Reload app config to get fresh settings
                fresh_app_config = load_app_config(os.getcwd())
                app_settings = fresh_app_config.get("app_settings", {})
                # Collect route information without importing modules
                _, modules_list = self._collect_route_information()
                return Response.success(data={
                    "app_settings": app_settings,
                    "modules": modules_list
                })
            except Exception as error:
                import traceback
                print(traceback.format_exc())
                print_error(f"Error retrieving app config: {error}")
                return Response.error(error)
        
        @app.route("/modules-list", methods=["GET"])
        def modules_list():
            try:
                # Collect module information without importing modules
                _, modules_list = self._collect_route_information()
                return Response.success(data={"modules": modules_list})
            except Exception as error:
                import traceback
                print(traceback.format_exc())
                print_error(f"Error retrieving modules list: {error}")
                return Response.error(error)
        
        @app.route("/routes", methods=["GET"])
        def routes():
            try:
                # Get route file information without importing
                routes_info, _ = self._collect_route_information()
                # Get serializable version of registered routes
                serializable_routes = self._get_serializable_routes()
                
                # Return both discovered file paths and registered routes
                return Response.success(data={
                    "endpoints": serializable_routes,
                    "route_files": routes_info
                })
            except Exception as error:
                import traceback
                print(traceback.format_exc())
                print_error(f"Error retrieving routes list: {error}")
                return Response.error(error)
            
    def register_schema_routes(self, app: Flask) -> None:
        """Register schema routes for all discovered schema files."""
        routes_path = os.path.join(os.getcwd(), self.routes_directory)
        
        # Only proceed if auto-registration is enabled
        if self.app_settings.get("automatically_register_schema_routes", True):
            # Find all schema files
            schema_files = find_schema_files(routes_path)
            
            # Register each schema route
            for route_path, _ in schema_files.items():
                # Skip if a route already exists
                schema_route = f"{route_path}/schema"
                if any(r.get('path') == schema_route for r in self.routes):
                    continue
                    
                # Create and register the route with dynamic schema loading
                route_info = {
                    "path": schema_route,
                    "endpoint": f"schema_{route_path.replace('/', '_')}",
                    "view_func": self._create_dynamic_schema_handler(route_path),
                    "methods": ["GET", "POST"]
                }
                self.routes.append(route_info)

    def _create_dynamic_schema_handler(self, route_path: str) -> Callable[[], FlaskResponse]:
        """Create a handler that dynamically loads schema data on each request.
        
        Args:
            route_path: The route path to load schema for
            
        Returns:
            Callable: A handler function that loads and returns schema data
        """
        def dynamic_schema_handler() -> FlaskResponse:
            try:
                # Get absolute path to schema file
                current_working_directory = os.getcwd()
                routes_directory = os.path.join(current_working_directory, self.routes_directory)
                schema_file_path = os.path.join(routes_directory, route_path.lstrip('/'), 'schema.json')
                
                # Check if file exists
                if not os.path.exists(schema_file_path):
                    return Response(
                        data={"schema": {}, "error": "Schema not found"}, 
                        status_code=404
                    )
                    
                # Read and parse schema file
                try:
                    with open(schema_file_path, 'r') as f:
                        schema_data = json.load(f)
                        
                    return Response(data={"schema": schema_data})
                except json.JSONDecodeError:
                    return Response(
                        data={"schema": {}, "error": "Invalid schema format"}, 
                        status_code=400
                    )
            except Exception as e:
                # Log and return error
                print_error(f"Error loading schema for {route_path}: {e}")
                return Response.error(
                    error=ManagedError(
                        error=e,
                        metadata={"route_path": route_path},
                        status_code=500
                    )
                )
        return dynamic_schema_handler

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
        
        # Register schema routes
        self.register_schema_routes(app)

        # Register error handlers
        self.register_error_handlers(app)
        
        # Register core routes
        self._register_core_routes(app)
        
        # Register all discovered routes
        for route in self.routes:
            app.add_url_rule(
                route["path"],
                endpoint=route["endpoint"],
                view_func=route["view_func"],
                methods=route.get("methods", ["POST"]),
                **{k: v for k, v in route.items() if k not in ["path", "endpoint", "view_func", "methods"]}
            )
            if self.environment in ["dev", "development"]:
                print(f"Registered route: {route['path']} with methods {route['methods']}")

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
                
                # Check if route path already exists before appending
                if not any(r['path'] == route_info['path'] for r in self.routes):
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
                print_error(f"Error registering route for {function.__name__}: {error}")
                raise
                
            @wraps(function)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return function(*args, **kwargs)
            return wrapper
        return decorator

