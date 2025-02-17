"""
Core functionality for Stacksync Workflows CDK.
Provides base classes and utilities for connector development.
"""


from .errors import ManagedError
from .responses import Response
from .request import  Request
from .dynamic_routing import Router

# Create the single global router instance


__all__ = [
    'Request',
    'Response',
    'ManagedError',
    'Router'
]
 