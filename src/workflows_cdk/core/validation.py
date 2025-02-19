from flask import request
from .errors import ManagedError
from typing import Any, List, Dict
import json
def validate_request(request: Any, required_fields: List[str]):
    """Validate that the request contains all required fields.
    
    Args:
        request: The Flask request object
        required_fields: List of field names that must be present in request.json
        
    Returns:
        The validated request.json data
        
    Raises:
        ManagedError: If validation fails
    """
    if not request.json:
        raise ManagedError("request body is empty")

    data = request.json["data"]
    credentials = request.json["credentials"]

    if not data or not credentials:
        raise ManagedError("Missing required fields: data or credentials")

    if required_fields:
        missing_fields = [field for field in required_fields if field not in request.json]
        if missing_fields:
            raise ManagedError(f"Missing required fields: {', '.join(missing_fields)}")


def parse_str_to_json(data):
    try:    
        return json.loads(data)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON string")

def validate_and_parse_json(data, field_name):
    if isinstance(data, str):
       return parse_str_to_json(data)
    elif isinstance(data, (dict, list)):
        return data
    else:
        raise ValueError(f"{field_name} must be a JSON string, dictionary, or list")

def validate_array(data, field_name):
    if isinstance(data, str):
        json_data = parse_str_to_json(data)
        if not isinstance(json_data, list):
            raise ValueError(f"{field_name} must be an array")
        return json_data
    elif isinstance(data, list):
        return data
    else:
        raise ValueError(f"{field_name} must be an array")

def validate_object(data, field_name):
    if isinstance(data, str):
        json_data = parse_str_to_json(data)
        if not isinstance(json_data, dict):
            raise ValueError(f"{field_name} must be an object")
        return json_data
    elif isinstance(data, dict):
        return data
    else:
        raise ValueError(f"{field_name} must be an object")

def validate_string(data, field_name):
    if not isinstance(data, str):
        raise ValueError(f"{field_name} must be a string")
    return data

def validate_dict(data, field_name):
    if not isinstance(data, dict):
        raise ValueError(f"{field_name} must be a dictionary")
