"""
Generates a list of modules based on discovered routes and configuration.
"""
import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional

def load_yaml_file(file_path: Path) -> Dict[str, Any]:
    """Safely load a YAML file."""
    if not file_path.exists():
        return {}
    try:
        with open(file_path, "r") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logging.warning(f"Failed to parse YAML file {file_path}: {e}")
        return {}
    except Exception as e:
        logging.warning(f"Error loading YAML file {file_path}: {e}")
        return {}

def generate_module_metadata(module_path_rel_str: str, routes_dir_abs_str: str, app_type: str) -> Optional[Dict[str, Any]]:
    """
    Generates information for a single module based on its relative path within the routes directory.

    Args:
        module_path_rel_str: The relative path string of the module's directory from the routes root.
        routes_dir_abs_str: The absolute path string of the routes directory.
        app_type: The type/name of the application.

    Returns:
        A dictionary containing module information, or None if generation fails.
    """
    try:
        # Reconstruct absolute path
        module_dir_abs = Path(routes_dir_abs_str) / module_path_rel_str
        module_type_path = module_dir_abs.parent

        # Construct config path using the absolute path
        config_path = module_dir_abs / "module_config.yaml"
        module_config = load_yaml_file(config_path)
        module_settings = module_config.get("module_settings", {})
        # Determine module attributes
        # module_type: From config, fallback to the parent directory name (of the absolute path)
        module_type = module_settings.get("module_type") or module_type_path.name
        if not module_type:
            logging.warning(f"Could not determine module_type for path {module_dir_abs}. Skipping.")
            return None # Cannot generate ID without module_type

        # module_category: From config, default to "action"
        module_category = module_settings.get("module_category", "action")

        # module_name: From config, default to capitalized module_type
        module_name = module_settings.get("module_name") or module_type.replace("_", " ").title()

        # module_version: From config, fallback to the module directory name (of the absolute path)
        module_version = module_settings.get("module_version") or module_dir_abs.name
        module_version = module_version.replace("v", "")
        if not module_version:
            logging.warning(f"Could not determine module_version for path {module_dir_abs}. Defaulting to 'latest'.")
            module_version = "latest" # Provide a default if detection fails

        # Format version for ID (replace '.' with '_')
        formatted_version = str(module_version).replace('.', '_')

        # Generate module_id: app_type-module_type-formatted_version
        module_id = f"{app_type}-{module_type}-{formatted_version}"

        module_data = {
            "module_id": module_id,
            "app_type": app_type,
            "module_type": module_type,
            "module_category": module_category,
            "module_name": module_name,
            "module_version": str(module_version), # Ensure version is string
            # Store the original relative path string for reference
            "module_path": module_path_rel_str
        }
        return module_data

    except Exception as e:
        # Log error with the relative path as it's the primary identifier received
        logging.error(f"Error generating module info for relative path {module_path_rel_str}: {e}")
        return None
