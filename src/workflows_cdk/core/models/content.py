"""
Content object handling for Flask applications.
"""

from typing import Any

from flask import Response, jsonify


class ContentObject:
    """
    Class representing a content object.

    This class encapsulates the data for a content object and provides
    methods for converting to the format expected by the frontend.
    """

    def __init__(
        self,
        id: str,
        data: list[dict[str, Any]],
        has_next_page: bool = False,
        next_cursor: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """
        Initialize a ContentObject.

        Args:
            id: The ID/name of the content object
            data: The data for the content object
            has_next_page: Whether there are more pages
            next_cursor: Cursor for pagination
            metadata: Optional metadata
        """
        self.id = id
        self.data = data
        self.has_next_page = has_next_page
        self.next_cursor = next_cursor
        self.metadata = metadata

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to the format expected by the frontend.

        Returns:
            dictionary representation of the ContentObject
        """
        result = {
            "id": self.id,
            "content": self.data,
            "pagination": {
                "has_next_page": self.has_next_page,
                "next_cursor": self.next_cursor,
            },
        }

        if self.metadata:
            result["metadata"] = self.metadata

        return result

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "ContentObject":
        """
        Create a ContentObject from a dictionary.

        Args:
            obj: dictionary containing content object data

        Returns:
            ContentObject instance
        """
        id_value = obj.get("id") or obj.get("content_object_name") or obj.get("name")
        if not id_value:
            raise ValueError(
                "Content object must have an id, content_object_name, or name"
            )

        data = obj.get("data") or obj.get("content") or []

        return cls(
            id=id_value,
            data=data,
            has_next_page=obj.get("has_next_page", False),
            next_cursor=obj.get("next_cursor"),
            metadata=obj.get("metadata"),
        )


def create_content_object(
    name: str,
    data: list[dict[str, Any]],
    has_next_page: bool = False,
    next_cursor: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a content object dictionary.

    Args:
        name: Name of the content object
        data: list of data items
        has_next_page: Whether there are more pages
        next_cursor: Cursor for pagination
        metadata: Optional metadata

    Returns:
        Content object dictionary
    """
    return {
        "content_object_name": name,
        "data": data,
        "has_next_page": has_next_page,
        "next_cursor": next_cursor,
        "metadata": metadata,
    }


def content_response(
    content_objects: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    status_code: int = 200,
) -> Response:
    """
    Create a Flask response with content objects.

    Args:
        content_objects: list of content objects created with create_content_object
                         or dictionaries with content_object_name and data keys
        metadata: Optional response metadata
        status_code: HTTP status code

    Returns:
        Flask response

    Example:
        ```python
        @app.route("/content", methods=["POST"])
        def content():
            # Option 1: Using create_content_object
            users = [
                {
                    "id": user_id,
                    "label": user_name
                }
            ]

            users_object = create_content_object("users", users)
            return content_response([users_object])

            # Option 2: Direct dictionary
            return content_response([
                {
                    "content_object_name": "users",
                    "data": users
                }
            ])
        ```
    """
    processed_objects = []

    for obj in content_objects:
        if not isinstance(obj, dict):
            continue

        # Get the content object name
        name = obj.get("content_object_name") or obj.get("name")
        if not name:
            continue

        # Get the data
        data = obj.get("data", [])

        # Create the content object in the format expected by the frontend
        content_obj = {
            "id": name,
            "content": data,
            "pagination": {
                "has_next_page": obj.get("has_next_page", False),
                "next_cursor": obj.get("next_cursor"),
            },
        }

        # Add metadata if present
        if obj.get("metadata"):
            content_obj["metadata"] = obj.get("metadata")

        processed_objects.append(content_obj)

    # Create the response
    response_data = {
        "data": {
            "content_objects": processed_objects,
            "pagination": {"has_more": False, "next_cursor": None},
        }
    }

    if metadata:
        response_data["metadata"] = metadata

    return jsonify(response_data), status_code
