"""
Core functionality for Stacksync Workflows CDK.
Provides base classes and utilities for connector development.
"""

from .router import ModuleRouter, init_app, get_router
from .errors import ManagedError
from .responses import Response
from .request import Request
from .app import create_app

from .dynamic_routing import Router

# Create the single global router instance


__all__ = [
    'create_app',
    'Request',
    'Response',
    'ManagedError',
    'Router',
    'ModuleRouter',
    'init_app'
]
 