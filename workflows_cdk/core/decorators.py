"""
Core decorators for module operations.
"""

import functools
import os
from typing import Any, Callable, List, Optional, Literal, Union
from functools import wraps

import sentry_sdk

from .errors import ManagedError
from .responses import Response
from .request import Request


ModuleCategory = Literal["action", "trigger"]


def module_route(
    *,
    category: ModuleCategory,
    required_fields: Optional[List[str]] = None,
    version: Optional[str] = None,
    methods: List[str] = ["POST"]
):
    """Decorator for module operations.
    
    Args:
        category: Module category (action/trigger)
        required_fields: Required input fields
        version: API version (defaults to folder name)
        methods: Allowed HTTP methods
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create request wrapper
            request = Request()
            
            # Set version from folder if not specified
            if not version:
                # Get version from folder structure
                module_path = func.__module__.split(".")
                if len(module_path) >= 2 and module_path[-2].startswith("v"):
                    request.version = module_path[-2]
            else:
                request.version = version
                
            # Set module category
            request.module_category = category
            
            # Validate required fields
            if required_fields and request.method == "POST":
                missing = [f for f in required_fields if f not in request.json]
                if missing:
                    raise ManagedError.validation_error(
                        f"Missing required fields: {', '.join(missing)}",
                        data={"missing_fields": missing}
                    )
            
            # Execute operation with our request wrapper
            result = func(request, *args, **kwargs)
            
            # Convert result to Response if needed
            if isinstance(result, tuple):
                return result  # Already a Response
            elif isinstance(result, dict):
                return Response.success(
                    data=result,
                    metadata={
                        "version": request.version,
                        "category": category
                    }
                )
            else:
                return result
                
        # Add metadata to function for route registration
        wrapper.methods = methods
        wrapper.version = version
        wrapper.category = category
        return wrapper
    
    return decorator 