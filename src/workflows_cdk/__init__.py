"""
Workflows CDK - A CDK for developing Stacksync Workflows Connectors
"""

__version__ = "0.0.1"
__author__ = "Stacksync"
__license__ = "Stacksync Connector License (SCL) v1.0"

from .core import *
from .core.app import create_app
from .core.request import Request
from .core.responses import Response
from .core.errors import ManagedError
from .core.router import ModuleRouter

# Create singleton router instance
router = ModuleRouter()

__all__ = [
    'create_app',
    'Request',
    'Response',
    'ManagedError',
    'router'
]