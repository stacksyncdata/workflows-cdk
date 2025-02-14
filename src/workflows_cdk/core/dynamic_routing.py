"""
Dynamic routing implementation for Flask applications.
Automatically discovers and registers routes based on your file system structure.
"""
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union, cast
from flask import Flask, request
import inspect
import os
import sys
import types
import importlib.util
from pathlib import Path
from workflows_cdk.core.errors import ManagedError
from workflows_cdk.core.responses import Response
import sentry_sdk

def wrap_route_handler(handler: Callable) -> Callable:
    """Simple wrapper for route handlers that adds error handling and response formatting."""
    @wraps(handler)
    def wrapped_handler(*args: Any, **kwargs: Any) -> Any:
        try:
            # Execute the handler
            result = handler(*args, **kwargs)
            
            # Convert dict responses to standard format
            if isinstance(result, dict):
                return Response.success(data=result)
            return result
            
        except ManagedError as e:
            # Handle known errors
            return Response.error(e)
        except Exception as e:
            # Log and handle unexpected errors
            print(f"Unhandled error in {handler.__name__}: {str(e)}")
            sentry_sdk.capture_exception(e)
            return Response.error(e, status_code=500)
            
    return wrapped_handler

class Router:
    """Flask File System Router that enables automatic route path detection based on file location."""
    
    def __init__(self, app: Optional[Flask] = None) -> None:
        """Initialize router with storage for routes."""
        # List to store all discovered routes
        self.routes: List[Dict[str, Any]] = []
        # Flask application instance
        self.app: Optional[Flask] = None
        self._router_instance = self
        
        if app is not None:
            self.init_app(app)

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
        routes_directory = Path(os.path.join(os.getcwd(), "routes"))
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
        
        # Create route information dictionary
        route_info = {
            "path": full_url_path,
            "endpoint": endpoint_name,
            "view_func": wrap_route_handler(function),
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
        
        # Construct the full path to your routes directory
        routes_directory = Path(os.path.join(current_working_directory, "routes"))
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


                                    # Update the route path based on the file's location in the routes directory
                                    # path_parts = list(route_file_path.parent.relative_to(routes_directory).parts)
                                    # if route_info["path"].startswith("/"):
                                    #     route_info["path"] = "/" + "/".join(path_parts) + route_info["path"]
                                    # route_options = {k:v for k,v in route_info.items() if k not in ["methods"]}
                                    # for key, value in route_options.items():
                                    #     route_info[key] = value


                                    self.routes.append(route_info)
                                    print(f"Found route: {route_info['path']} with methods: [{','.join(route_info['methods'])}]")
                    
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
        
        @app.errorhandler(ManagedError)
        def handle_managed_error(error: ManagedError):
            app.logger.error(f"Managed error: {error.error}")
            return Response.error(error)
        
        @app.errorhandler(Exception)
        def handle_error(error: Exception):
            print(f"Unhandled error: {str(error)}")
            app.logger.error(f"Unhandled error: {str(error)}")
            sentry_sdk.capture_exception(error)
            return Response.error(error, status_code=500)

    def init_app(self, app: Flask) -> None:
        """Initialize the router with a Flask app and register all discovered routes."""
        self.app = app
        
        # First discover all routes in the project
        self.discover_routes()

        self.register_error_handlers(app)
    
        # Register each discovered route with Flask
        for route_info in self.routes:
            print(f"Registering route: {route_info['path']} with methods: [{','.join(route_info['methods'])}] -> {route_info['endpoint']}")
            app.add_url_rule(
                route_info["path"],
                endpoint=route_info["endpoint"],
                view_func=route_info["view_func"],
                methods=route_info["methods"],
                **route_info["options"]
                # **{k: v for k, v in route_info.items() if k not in ["path", "endpoint", "view_func", "methods"]}
            )
            print(f"Successfully registered route: {route_info['path']} with methods: [{','.join(route_info['methods'])}] -> {route_info['endpoint']}")
        
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

            # Get the file path of the module containing this function
            function_module = inspect.getmodule(function)
            if not function_module or not function_module.__file__:
                raise ValueError("Could not determine the module path for the function")
                
            # Get base path from the file's location
            try:
                routes_directory = Path(os.path.join(os.getcwd(), "routes"))
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
                wrapped_function = wrap_route_handler(function)
                # Create route information dictionary
                route_info = {
                    "path": full_url_path,
                    "endpoint": endpoint_name,
                    "view_func": wrapped_function,
                    "methods": http_methods,
                    "options": options
                }

                # route_info = self._create_route_info(function, rule, options)

                
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
                        **route_info["options"]
                        # **{k: v for k, v in route_info.items() if k not in ["path", "endpoint", "view_func", "methods"]}
                    )
                    print(f"Registered new route: {route_info['path']} with methods: [{','.join(route_info['methods'])}] -> {route_info['endpoint']}")
                
            except Exception as error:
                print(f"Error registering route for {function.__name__}: {error}")
                raise
                
            @wraps(function)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return function(*args, **kwargs)
            return wrapper
        return decorator

