"""
Centralized Sentry error handling for the Workflows CDK.
"""

import os
import traceback

import requests
import sentry_sdk
from flask import Flask
from sentry_sdk.integrations.flask import FlaskIntegration


def append_external_request_info(event, hint):
    """Add external request information to the event."""
    try:
        exc_info = hint.get("exc_info")
        if exc_info:
            _, exception_value, _ = exc_info
            if isinstance(exception_value, requests.exceptions.RequestException):
                response = getattr(exception_value, "response", None)
                if response is not None:
                    event.setdefault("extra", {})
                    event["extra"]["api_url"] = (
                        response.url if hasattr(response, "url") else "Unknown URL"
                    )
                    event["extra"]["http_status"] = response.status_code
                    event["extra"]["response_body"] = response.text
                    event["extra"]["headers"] = dict(response.headers)
    except Exception as e:
        print(f"Error appending request info: {e}")
    return event


def append_path_params(event, hint):
    """Add path parameters to the event."""
    try:
        event.setdefault("tags", {})
        request = event.get("request", {})
        path = request.get("url", "")
        if path:
            # Remove query parameters and protocol
            path = path.split("?")[0]
            path = path.split("//")[-1] if "//" in path else path

            # Split path into components
            path_components = [p for p in path.split("/") if p][
                2:
            ]  # Skip domain and version

            # URL path to variable name mapping
            url_mapping = {
                "routes": "route_id",
                "workflows": "workflow_id",
                "modules": "module_id",
                "schemas": "schema_id",
                "connections": "connection_id",
                "variables": "variable_id",
            }

            # Create path dictionary
            path_dict = {}
            path_components = [c for c in path_components if c != "id"]
            for i in range(len(path_components) - 1):
                if path_components[i] in url_mapping:
                    path_dict[url_mapping[path_components[i]]] = path_components[i + 1]

            # Add path parameters as tags
            for key, value in path_dict.items():
                event["tags"][key] = value

    except Exception as e:
        print(f"Error appending path params: {e}")
    return event


def before_send(event, hint):
    """Process and enrich Sentry events before sending.

    Args:
        event: The event to be sent to Sentry
        hint: A dictionary of hints about the event

    Returns:
        The processed event or None to drop the event
    """
    try:
        # Add basic error information
        exc_info = hint.get("exc_info")
        if exc_info:
            exception_type, exception_value, _ = exc_info

            # Add exception details to event context
            event.setdefault("extra", {})
            event["extra"]["exception_type"] = str(exception_type.__name__)
            event["extra"]["exception_value"] = str(exception_value)

            # Extract and add traceback information
            if hasattr(exception_value, "__traceback__"):
                tb_summary = "".join(traceback.format_tb(exception_value.__traceback__))
                event["extra"]["traceback_summary"] = str(tb_summary)

        # Initialize tags if not present
        event.setdefault("tags", {})

        # Extract request information if available
        request = event.get("request", {})
        if request:
            # Add request method and URL
            event["tags"]["http_method"] = str(request.get("method", "unknown"))
            event["tags"]["request_url"] = str(request.get("url", "unknown"))

            # Process query parameters
            query_string = request.get("query_string", "")
            if query_string:
                try:
                    # Parse and add query parameters as tags
                    if isinstance(query_string, bytes):
                        query_string = query_string.decode()
                    query_params = dict(
                        item.split("=")
                        for item in query_string.split("&")
                        if "=" in item
                    )
                    for key, value in query_params.items():
                        event["tags"][f"query_{key}"] = str(value)
                except Exception:
                    pass

        # Extract route information from stack frames
        exception = event.get("exception", {})
        values = exception.get("values", [])

        for value in values:
            frames = value.get("stacktrace", {}).get("frames", [])

            for frame in frames:
                file_path = str(frame.get("filename", ""))
                function_name = str(frame.get("function", ""))

                # Extract module/route information
                if "/routes/" in file_path:
                    route_path = file_path.split("/routes/")[1].split(".")[0]
                    event["tags"]["route_path"] = route_path

                # Extract function information
                if function_name:
                    event["tags"]["function"] = function_name

                # Add module information
                if file_path:
                    event["tags"]["module"] = file_path.split("/")[-1]

        # Add external request information
        event = append_external_request_info(event, hint)

        # Add path parameters
        event = append_path_params(event, hint)

    except Exception as e:
        # Log error but don't block event sending
        print(f"Error in before_send: {e}")

    return event


def init_sentry(app: Flask, dsn: str | None = None) -> None:
    """Initialize Sentry with the given configuration."""
    sentry_dsn = dsn or app.config.get("sentry_dsn")

    if not sentry_dsn or not isinstance(sentry_dsn, str):
        app.logger.info("Sentry disabled - no valid DSN")
        return

    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration()],
        environment=os.getenv("ENVIRONMENT", "development"),
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        before_send=before_send,
        include_local_variables=True,
        attach_stacktrace=True,
        send_default_pii=False,
        include_source_context=True,
        debug=False,
    )
    app.logger.info("Sentry initialized successfully")
