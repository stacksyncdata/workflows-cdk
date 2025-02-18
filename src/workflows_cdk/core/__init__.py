"""
Core functionality for Stacksync Workflows CDK.
Provides base classes and utilities for connector development.
"""

import logging

# Configure logging for the CDK
logger = logging.getLogger('workflows_cdk')
logger.setLevel(logging.DEBUG)

# Add a stream handler if none exists
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('Workflows CDK | %(levelname)s - %(message)s'))
    logger.addHandler(handler)

from .errors import ManagedError
from .responses import Response
from .request import Request
from .dynamic_routing import Router

# Create the single global router instance


__all__ = [
    'Request',
    'Response',
    'ManagedError',
    'Router'
]
 