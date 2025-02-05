"""
Example Slack connector implementation using the Workflows CDK.
"""

import os
from typing import Any, Dict, List, Tuple
from datetime import datetime

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from workflows_cdk.src.core.connector import BaseConnector
from workflows_cdk.src.core.types import ConnectorConfig, SchemaFieldType, SchemaField
from pydantic import BaseModel, Field


# Load environment variables
load_dotenv()

# Get configuration from environment
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5001"))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"


class SlackField(BaseModel):
    """Schema field for Slack connector."""
    type: SchemaFieldType = Field(..., description="Field type")
    label: str = Field(..., description="Human-readable label")
    description: str = Field(None, description="Field description")
    required: bool = Field(default=False, description="Whether the field is required")
    default: Any = Field(default=None, description="Default value")
    options: List[Dict[str, str]] = Field(default=None, description="Options for select fields")


class SlackConnector(BaseConnector):
    """Slack connector for sending messages and managing channels."""
    
    def setup(self) -> None:
        """Set up the Slack connector."""
        # Initialize Slack client
        token = os.getenv("SLACK_BOT_TOKEN")
        if not token:
            raise ValueError("SLACK_BOT_TOKEN environment variable is required")
            
        self.client = WebClient(token=token)
        
        # Register schema
        self.schema_manager.register_schema(
            schema={
                "message": [
                    SchemaField(
                        name="channel",
                        type=SchemaFieldType.SELECT,
                        label="Channel",
                        description="Select channel to send message to",
                        required=True,
                        options=self._get_channels()
                    ),
                    SchemaField(
                        name="message",
                        type=SchemaFieldType.TEXT,
                        label="Message",
                        description="Message to send",
                        required=True
                    ),
                    SchemaField(
                        name="thread_ts",
                        type=SchemaFieldType.TEXT,
                        label="Thread Timestamp",
                        description="Optional thread to reply to",
                        required=False
                    )
                ]
            },
            ui_schema={
                "message": {
                    "ui:order": ["channel", "message", "thread_ts"],
                    "ui:description": "Send a message to a Slack channel"
                }
            }
        )
        
    def _get_channels(self) -> List[Dict[str, str]]:
        """Get list of available channels."""
        try:
            response = self.client.conversations_list()
            return [
                {"value": channel["id"], "label": channel["name"]}
                for channel in response["channels"]
                if channel["is_member"]
            ]
        except SlackApiError as e:
            return []  # Return empty list on error
            
    def handle_execute(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle message sending requests."""
        try:
            # Extract data
            channel = data["channel"]
            message = data["message"]
            thread_ts = data.get("thread_ts")
            
            # Send message
            response = self.client.chat_postMessage(
                channel=channel,
                text=message,
                thread_ts=thread_ts
            )
            
            return {
                "message_ts": response["ts"],
                "channel": response["channel"],
                "message": message
            }
            
        except SlackApiError as e:
            raise Exception(f"Failed to send message: {str(e)}")
            
    def handle_content(
        self,
        data: Dict[str, Any]
    ) -> Tuple[Any, str, Dict[str, Any]]:
        """Handle content requests (e.g., message history)."""
        try:
            # Get message history
            channel = data["channel"]
            limit = data.get("limit", 100)
            
            response = self.client.conversations_history(
                channel=channel,
                limit=limit
            )
            
            return (
                response["messages"],
                "application/json",
                {
                    "channel": channel,
                    "count": len(response["messages"]),
                    "has_more": response["has_more"],
                    "retrieved_at": datetime.utcnow().isoformat()
                }
            )
            
        except SlackApiError as e:
            raise Exception(f"Failed to get message history: {str(e)}")


def main():
    """Run the Slack connector."""
    config = ConnectorConfig(
        name="slack-connector",
        version="1.0.0",
        description="Slack connector for sending messages and managing channels",
        author="Stacksync",
        auth_required=True,
        auth_type="bot_token"
    )
    
    connector = SlackConnector(config, host=HOST, port=PORT)
    connector.run(debug=DEBUG)


if __name__ == "__main__":
    main() 