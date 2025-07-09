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
from .homepage_template import get_homepage_template
from contextlib import contextmanager
import gc
import re



def load_app_config(app_dir: str) -> Dict[str, Any]:
    """Load app config with proper file handle cleanup."""
    config_path = os.path.join(app_dir, "app_config.yaml")
    if not os.path.exists(config_path):
        return {}
        
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError, ValueError):
        return {}

def load_schema_file(schema_path: str) -> Optional[Dict[str, Any]]:
    """Load schema file with explicit resource cleanup.
    
    """
    if not os.path.exists(schema_path):
        return None
        
    try:
        with open(schema_path, 'r') as f:
            schema_data = json.load(f)
            
        if not isinstance(schema_data, dict):
            return None
            
        return schema_data
    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse schema file {schema_path}: {e}")
        return None
    except Exception as e:
        logging.warning(f"Error loading schema file {schema_path}: {e}")
        return None

def find_schema_paths(directory: str) -> List[str]:
    """Find schema.json file paths without loading content.

    
    Args:
        directory: Root directory to search from
        
    Returns:
        List[str]: List of route paths that have schema files
    """
    schema_paths = []
    try:
        for root, _, files in os.walk(directory):
            if 'schema.json' in files:
                # Calculate route path without loading the file
                rel_path = os.path.relpath(root, directory)
                path_parts = rel_path.split(os.sep)
                path_parts = [part.replace(" ", "_") for part in path_parts]
                route_path = '/' + '/'.join(path_parts)
                if route_path == '/.':
                    route_path = ''
                schema_paths.append(route_path)
                    
    except Exception as e:
        logging.error(f"Error scanning for schema paths: {e}")
        
    return schema_paths



def is_production_environment() -> bool:
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
    tb_string = ""
    
    # Only capture in Sentry once and handle gracefully
    try:
        sentry_sdk.capture_exception(error)
    except Exception as sentry_error:
        print_error(f"Error capturing exception in Sentry: {sentry_error}")
    
    # Only log errors in non-production environments
    if not is_production_environment():
        try:
            exc_info = sys.exc_info()
            if exc_info[0] is None:  # If no current exception context, create one from the error
                exc_info = (type(error), error, error.__traceback__)
            
            tb_string = ''.join(traceback.format_exception(*exc_info))
            # Log the full traceback
            app.logger.error("Traceback: %s", tb_string)
            print_error(f"Error: {error}")
        except Exception as log_error:
            print_error(f"Error during logging: {log_error}")
   
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
            # Log unexpected errors and convert to ManagedError
            log_error_details(current_app, unhandled_error)
            raise ManagedError(
                error=f"Internal server error: {str(unhandled_error)}",
                metadata={
                    "type": "internal_error",
                    "original_error": str(unhandled_error)
                },
                status_code=500
            ) from unhandled_error

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
        
        # Initial app config loading
        self.app_config = load_app_config(os.getcwd())
        self.config = config or {}
        self.sentry_dsn = sentry_dsn
        self.cors_origins = cors_origins or ["*"]
        
        # Apply configuration settings
        self.refresh_app_config_variables(self.app_config)

        if app is not None:
            self.init_app(app)

    def refresh_app_config_variables(self, app_config: Dict[str, Any]) -> None:
        """Apply configuration settings to the router instance.
        
        This function centralizes the logic for applying configuration settings,
        making it reusable across initialization and configuration refreshes.
        
        Args:
            app_config: The application configuration dictionary
        """
        # Extract key settings sections
        self.app_config = app_config
        self.app_settings = app_config.get("app_settings", {})
        self.local_development_settings = app_config.get("local_development_settings", {})
        
        # Apply core settings
        self.app_type = self.app_settings.get("app_type", "unknown_app")
        self.port = self.local_development_settings.get("port") or self.app_settings.get("port") or 2003
        self.debug = self.local_development_settings.get("debug", True) or self.app_settings.get("debug", True)
        
        # Apply Sentry and CORS settings with override priority
        self.sentry_dsn = self.app_settings.get("sentry_dsn") or self.local_development_settings.get("sentry_dsn")
        self.cors_origins = self.local_development_settings.get("cors_origins") or ["*"]
        
        # Determine routes directory
        routes_directory_possible_key_names = ["routes_directory_path", "routes_directory", "routes_dir", "routes_path"]
        self.routes_directory = next(
            (self.app_settings[key] for key in routes_directory_possible_key_names if key in self.app_settings),
            "src/routes"
        )

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
            # Replace spaces with underscores in each path part
            path_parts = [part.replace(" ", "_") for part in path_parts]
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
        # Only include .py files that are directly inside a version directory (v1, v2, vX, etc.)
        version_dir_pattern = re.compile(r"^v[\w\d]+$")
        route_files = []
        for path in routes_directory.rglob("*.py"):
            if path.name == "__init__.py":
                continue

            # Get the relative parts from routes directory
            path_parts = path.parts
            routes_dir_parts = routes_directory.parts
            relative_parts = path_parts[len(routes_dir_parts):]

            # We want: .../<module>/<version>/file.py (relative_parts = [module, version, file.py])
            # So only include if len(relative_parts) == 3 and relative_parts[1] matches version pattern
            if len(relative_parts) == 3 and version_dir_pattern.match(relative_parts[1]):
                route_files.append(path)
            # Otherwise, skip (this includes any file in subdirs of version dirs)
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

    def _route_exists(self, path: str) -> bool:
        """Check if a route with the given path already exists."""
        return any(r.get('path') == path for r in self.routes)
    
    def _add_route_if_not_exists(self, route_info: Dict[str, Any]) -> bool:
        """Add route only if it doesn't already exist. Returns True if added."""
        if not self._route_exists(route_info['path']):
            self.routes.append(route_info)
            return True
        return False

    def clear_accumulated_data(self) -> None:
        """
        Clear accumulated data to prevent memory accumulation in serverless environments.
        """
        # Keep only essential routes (everything else can be rediscovered)
        core_paths = ['/health', '/app-config', '/modules-list', '/routes', '/']
        
        # Filter out schema routes and user routes (they end with /schema or are user-defined)
        essential_routes = []
        for route in self.routes:
            path = route.get('path', '')
            # Keep core routes only
            if path in core_paths:
                essential_routes.append(route)
            # Remove schema routes (they'll be re-registered)
            # Remove user routes (they'll be rediscovered)
        
        self.routes = essential_routes
        
        # Clear module metadata (it holds file paths and other references)
        self.modules_list.clear()
        
        # Force Python to clean up now (don't wait for automatic GC)
        gc.collect()

    def discover_routes(self) -> None:
        """
        Discover routes while preventing memory accumulation.
        
        Key issue: Each discovery loads Python modules that stay in memory forever.
        In serverless, this grows with each container reuse.
        """
        current_working_directory = os.getcwd()
        
        # Collect route info without any imports first
        routes_info, module_list = self._collect_route_information()
        
        # Add module metadata (but clear old references first)
        for module in module_list:
            if not any(m.get("module_id") == module["module_id"] for m in self.modules_list):
                self.modules_list.append(module)
        
        if not routes_info:
            return

        # Add working directory to path for imports
        if current_working_directory not in sys.path:
            sys.path.insert(0, current_working_directory)

        # Use clean import context to prevent module accumulation
        with clean_module_import():
            # Set up temporary main module for route discovery
            original_router_module = sys.modules.get('main', None)
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
                                    self._add_route_if_not_exists(route_info)
                        
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
        @app.route("/", methods=["GET"])
        def root():
            # Get the connector name from the app settings
            connector_name = self.app_settings.get("app_name", "Stacksync Connector")
            
            # HTML template with Stacksync logo and connector name
            html = get_homepage_template(connector_name, self.app_type, self.environment)
            return html

        @app.route("/health", methods=["GET"])
        def health_check():
            return Response.success(data={"status": "healthy"})
        
        @app.route("/app-config", methods=["GET"])
        def app_config():
            try:
                # Reload app config to get fresh settings
                fresh_app_config = load_app_config(os.getcwd())
                
                # Apply the fresh configuration
                self.refresh_app_config_variables(fresh_app_config)
                
                # Refresh modules list
                _, modules_list = self._collect_route_information()
                
                # Return updated config
                return Response.success(data={
                    "app_settings": self.app_settings,
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
                _, modules_list_data = self._collect_route_information()
                
                # Ensure we return a clean response without potential circular references
                clean_modules = []
                for module in modules_list_data:
                    if isinstance(module, dict):
                        # Only include serializable data
                        clean_module = {
                            key: value for key, value in module.items()
                            if isinstance(value, (str, int, float, bool, list, dict, type(None)))
                        }
                        clean_modules.append(clean_module)
                
                return Response.success(data={"modules": clean_modules})
            except Exception as error:
                print_error(f"Error retrieving modules list: {error}")
                return Response.error(
                    error=f"Failed to retrieve modules list: {str(error)}",
                    status_code=500
                )
        
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
        """Register schema routes without loading schema content into memory."""
        routes_path = os.path.join(os.getcwd(), self.routes_directory)

        # Only proceed if auto-registration is enabled
        if self.app_settings.get("automatically_register_schema_routes", True):
            schema_paths = find_schema_paths(routes_path)

            # Register each schema route
            for route_path in schema_paths:
                self._register_schema_route(route_path, app)

    def _handle_dynamic_schema_request(self, dynamic_path: str) -> FlaskResponse:
        """Handle schema requests for paths that might not have been registered at startup.
        
        This is a catch-all handler that will check if a schema.json file exists for the
        requested path and return it if found, even if it was added after startup.
        
        Args:
            dynamic_path: The dynamic part of the path (everything before /schema)
            
        Returns:
            FlaskResponse: The schema response
        """
        try:
            # Construct the full path to the schema file
            current_working_directory = os.getcwd()
            routes_directory = os.path.join(current_working_directory, self.routes_directory)
            schema_file_path = os.path.join(routes_directory, dynamic_path, 'schema.json')
            
            # Check if the schema file exists
            if not os.path.exists(schema_file_path):
                return Response(
                    data={"schema": {}, "error": f"Schema not found for {dynamic_path}"}, 
                    status_code=404
                )
            
            # Load the schema file
            try:
                with open(schema_file_path, 'r') as f:
                    schema_data = json.load(f)
                
                # Log discovery of new schema
                if self.environment in ["dev", "development"]:
                    if not any(r.get('path') == f"/{dynamic_path}/schema" for r in self.routes):
                        print(f"Dynamically served schema for new path: /{dynamic_path}/schema")
                
                return Response(data={"schema": schema_data})
            except json.JSONDecodeError:
                return Response(
                    data={"schema": {}, "error": f"Invalid schema format for {dynamic_path}"}, 
                    status_code=400
                )
        except Exception as e:
            # Log and return error
            print_error(f"Error handling dynamic schema for {dynamic_path}: {e}")
            return Response.error(
                error=ManagedError(
                    error=e,
                    metadata={"dynamic_path": dynamic_path},
                    status_code=500
                )
            )
    
    def _create_dynamic_schema_handler(self, route_path: str) -> Callable[[], FlaskResponse]:
        """Create a handler that dynamically loads schema data on each request.
        
        For routes registered at startup.
        
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

    def _register_schema_route(self, route_path: str, app: Optional[Flask] = None) -> None:
        """Register a schema route for the given path.
        
        Args:
            route_path: The route path to load schema for
            app: The Flask app to register with (if None, just adds to routes list)
        """
        schema_route = f"{route_path}/schema"
        
        # Create route info
        route_info = {
            "path": schema_route,
            "endpoint": f"schema_{route_path.replace('/', '_')}",
            "view_func": self._create_dynamic_schema_handler(route_path),
            "methods": ["GET", "POST"]
        }
        
        # Add route only if it doesn't exist (consistent duplicate checking)
        added = self._add_route_if_not_exists(route_info)
        
        # If app is provided and route was added, register immediately
        if app is not None and added and hasattr(app, 'add_url_rule'):
            app.add_url_rule(
                route_info["path"],
                endpoint=route_info["endpoint"],
                view_func=route_info["view_func"],
                methods=route_info["methods"]
            )
            if self.environment in ["dev", "development"]:
                print(f"Registered schema route: {route_info['path']} with methods {route_info['methods']}")

    def init_app(self, app: Flask) -> None:
        """Initialize the router with a Flask app and register all discovered routes."""
        self.app = app
        
        self.clear_accumulated_data()
        
        self.app_config = load_app_config(os.getcwd())
        self.refresh_app_config_variables(self.app_config)
        
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
        
        # Register a catch-all route for dynamic schema discovery
        # This will handle any schema requests for paths that don't have explicit routes
        app.add_url_rule(
            "/<path:dynamic_path>/schema",
            endpoint="dynamic_schema_handler",
            view_func=self._handle_dynamic_schema_request,
            methods=["GET", "POST"]
        )

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
                
                # Add route only if it doesn't exist
                self._add_route_if_not_exists(route_info)
          
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

@contextmanager
def clean_module_import():
    """
    Simple context manager that cleans up imported modules.
    
    The real issue: Python keeps ALL imported modules in memory forever.
    In serverless, this means each route discovery adds to memory permanently.
    """
    modules_before = set(sys.modules.keys())
    path_before = sys.path[:]
    
    try:
        yield
    finally:
        # Remove any new modules (they're just route files, don't need to persist)
        new_modules = set(sys.modules.keys()) - modules_before
        for module_name in new_modules:
            sys.modules.pop(module_name, None)
        
        # Reset path
        sys.path[:] = path_before
        
        # Force cleanup of module references
        gc.collect()
