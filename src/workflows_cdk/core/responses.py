"""
Response handling module for Flask applications.
Provides standardized response formatting and error handling.
"""

import os
from datetime import datetime
from typing import Any

from flask import Response as FlaskResponse
from flask import jsonify, make_response
from werkzeug.exceptions import HTTPException

from .errors import ManagedError
from .get_environment import get_environment


class Response:
    """Standardized response class for API endpoints."""

    environment = get_environment()
    # Cache environment check
    _IS_PRODUCTION = environment == "prod" or environment == "stage"

    @staticmethod
    def create_response(
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> FlaskResponse:
        """Create a standardized response."""
        response_data = {"data": data}
        if metadata:
            response_data["metadata"] = metadata
        return make_response(jsonify(response_data), status_code)

    def __new__(
        cls,
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> FlaskResponse:
        """Create a new success response."""
        return cls.create_response(data, metadata, status_code)

    @classmethod
    def success(
        cls,
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> FlaskResponse:
        """Create a success response."""
        return cls.create_response(data, metadata, status_code)

    @classmethod
    def content(
        cls,
        content_objects: list[Any],
        metadata: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> FlaskResponse:
        """Create a response with content objects.

        Args:
            content_objects: list of ContentObject instances or dictionaries
            metadata: Optional metadata for the response
            status_code: HTTP status code

        Returns:
            Flask response with content objects

        Example:
            ```python
            @app.route("/content", methods=["POST"])
            def content():
                users = [
                    {
                        "id": user_id,
                        "label": user_name
                    }
                ]

                content_objects = [
                    ContentObject(id="users", data=users)
                ]

                return Response.content(content_objects)
            ```
        """
        # Import here to avoid circular imports
        from workflows_cdk.core.models.content import ContentObject

        processed_objects = []

        for obj in content_objects:
            if isinstance(obj, ContentObject):
                processed_objects.append(obj.to_dict())
            elif isinstance(obj, dict):
                try:
                    content_obj = ContentObject.from_dict(obj)
                    processed_objects.append(content_obj.to_dict())
                except ValueError:
                    # If it's already in the right format, use it directly
                    if "id" in obj and "content" in obj:
                        processed_objects.append(obj)

        data = {
            "content_objects": processed_objects,
            "pagination": {"has_more": False, "next_cursor": None},
        }

        return cls.create_response(data, metadata, status_code)

    @classmethod
    def error(
        cls,
        error: ManagedError | Exception | str,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> FlaskResponse:
        """Create an error response with environment-appropriate detail level."""

        # Get stack trace for non-production environments
        stack_trace = None
        if not cls._IS_PRODUCTION and isinstance(error, Exception):
            import traceback

            stack_trace = traceback.format_exc()

        if data:
            if isinstance(data, str):
                data = {"error": data}

        if metadata:
            if isinstance(metadata, str):
                metadata = {"metadata": metadata}

        # Base metadata
        base_metadata = {
            "timestamp": datetime.now().isoformat(),
            "environment": os.getenv("ENVIRONMENT", "development"),
            # "event_id": event_id,
            "stack_trace": stack_trace if not cls._IS_PRODUCTION else None,
            **(metadata or {}),
        }

        # Merge with error metadata if available
        metadata = base_metadata
        if isinstance(error, ManagedError) and error.metadata:
            metadata = {**base_metadata, **(error.metadata or {})}

        if isinstance(error, ManagedError):
            response_data: dict[str, Any] = {
                "error": str(error.error),
            }
            if error.data:
                response_data["data"] = error.data
            if metadata:
                response_data["metadata"] = metadata
        elif isinstance(error, HTTPException):
            status_code = error.code or status_code
            response_data: dict[str, Any] = {
                "error": error.description,
                "data": {"code": error.code, "name": error.name},
            }
            if metadata:
                response_data["metadata"] = metadata
        else:
            response_data: dict[str, Any] = {
                "error": str(error),
                "data": data if data else {},
                "metadata": metadata if metadata else {},
                "status_code": status_code if status_code else 400,
            }

        # Override with provided data and metadata if present
        if data:
            response_data["data"] = data if isinstance(data, dict) else {"error": data}
        elif "data" in response_data and not response_data.get("data"):
            response_data["data"] = {}

        if metadata:
            response_data["metadata"] = (
                metadata if isinstance(metadata, dict) else {"metadata": metadata}
            )
        elif "metadata" in response_data and not response_data.get("metadata"):
            response_data["metadata"] = {}

        return make_response(jsonify(response_data), status_code)
