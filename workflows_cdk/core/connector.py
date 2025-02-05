"""
Base connector implementation for Stacksync Workflows CDK.
Provides core functionality and interface for building connectors.
"""

from typing import Any, Dict, Optional, Tuple
from abc import ABC, abstractmethod

from .types import ConnectorConfig
from .schema import SchemaManager
from .router import ConnectorRouter


class BaseConnector(ABC):
    """Base class for implementing Stacksync connectors."""
    
    def __init__(
        self,
        config: ConnectorConfig,
        host: str = "0.0.0.0",
        port: int = 5000
    ):
        """Initialize the connector.
        
        Args:
            config: Connector configuration
            host: Host to bind to
            port: Port to listen on
        """
        self.config = config
        self.host = host
        self.port = port
        
        # Initialize components
        self.schema_manager = SchemaManager(config)
        self.router = ConnectorRouter(config, self.schema_manager)
        
        # Register handlers
        self.router.register_execute_handler(self.handle_execute)
        self.router.register_content_handler(self.handle_content)
        
        # Setup
        self.setup()
        
    @abstractmethod
    def setup(self) -> None:
        """Set up the connector.
        
        This method should be implemented to:
        1. Register schemas using self.schema_manager.register_schema()
        2. Initialize any necessary resources
        3. Set up authentication if required
        """
        pass
        
    @abstractmethod
    def handle_execute(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle execute requests.
        
        Args:
            data: Validated request data
            
        Returns:
            Execution results
        """
        pass
        
    @abstractmethod
    def handle_content(
        self,
        data: Dict[str, Any]
    ) -> Tuple[Any, str, Dict[str, Any]]:
        """Handle content requests.
        
        Args:
            data: Request data
            
        Returns:
            Tuple of (content_data, content_type, metadata)
        """
        pass
        
    def run(self, **kwargs) -> None:
        """Run the connector service.
        
        Args:
            **kwargs: Additional arguments passed to Flask run
        """
        self.router.run(
            host=self.host,
            port=self.port,
            **kwargs
        ) 