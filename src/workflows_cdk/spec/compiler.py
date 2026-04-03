"""
Compiler: turns a ``ConnectorSpec`` into a scaffolded CDK project on disk.

The generated project is immediately runnable with ``./run_dev.sh`` and
follows every convention documented in the Stacksync Workflows platform
(module schema v1.0.0, /execute + /content + /schema endpoints, Docker
deployment, file-based route discovery under ``src/modules/``).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Optional

import yaml

from .connector_spec import ActionSpec, AuthSpec, ConnectorSpec, FieldSpec, TriggerSpec

MODULES_DIR = "src/modules"
DEFAULT_PORT = 2003


def compile_connector(spec: ConnectorSpec, output_dir: Path) -> Path:
    """Write a full CDK project to *output_dir* / *spec.directory_name*.

    Returns the root directory of the generated project.
    """
    project_dir = output_dir / spec.directory_name
    project_dir.mkdir(parents=True, exist_ok=True)

    _write_main_py(spec, project_dir)
    _write_app_config(spec, project_dir)
    _write_requirements(project_dir)
    _write_capability_yaml(spec, project_dir)
    _write_deployment_files(spec, project_dir)

    for action in spec.actions:
        _write_action_route(spec, action, project_dir)

    for trigger in spec.triggers:
        _write_trigger_route(spec, trigger, project_dir)

    return project_dir


def preview_tree(spec: ConnectorSpec) -> str:
    """Return a textual file-tree preview without writing anything."""
    lines = [f"{spec.directory_name}/"]
    lines.append("  main.py")
    lines.append("  app_config.yaml")
    lines.append("  requirements.txt")
    lines.append("  capability.yaml")
    lines.append("  Dockerfile")
    lines.append("  run_dev.sh")
    lines.append("  config/")
    lines.append("    Dockerfile.dev")
    lines.append("    entrypoint.sh")
    lines.append("    gunicorn_config.py")
    lines.append(f"  {MODULES_DIR}/")

    for action in spec.actions:
        lines.append(f"    {action.name}/")
        lines.append(f"      {spec.version}/")
        lines.append(f"        route.py")
        lines.append(f"        schema.json")
        lines.append(f"        module_config.yaml")

    for trigger in spec.triggers:
        lines.append(f"    {trigger.name}/")
        lines.append(f"      {spec.version}/")
        lines.append(f"        route.py")
        lines.append(f"        schema.json")
        lines.append(f"        module_config.yaml")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Static project files
# ---------------------------------------------------------------------------

def _write_main_py(spec: ConnectorSpec, project_dir: Path) -> None:
    slug = spec.app_type.replace("-", "_")
    content = textwrap.dedent(f"""\
        from flask import Flask
        from workflows_cdk import Router

        app = Flask("{slug}")
        router = Router(app)

        if __name__ == "__main__":
            router.run_app(app)
    """)
    (project_dir / "main.py").write_text(content)


def _write_app_config(spec: ConnectorSpec, project_dir: Path) -> None:
    config = {
        "app_settings": {
            "app_type": spec.app_type,
            "app_name": spec.app_name,
            "app_icon_svg_url": "",
            "app_description": f"Stacksync connector for {spec.app_name}",
            "routes_directory": MODULES_DIR,
        },
        "local_development_settings": {
            "sentry_dsn": "",
            "cors_origins": ["*"],
            "routes_directory": MODULES_DIR,
            "debug": True,
            "host": "0.0.0.0",
            "port": DEFAULT_PORT,
        },
    }
    (project_dir / "app_config.yaml").write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False)
    )


def _write_requirements(project_dir: Path) -> None:
    content = textwrap.dedent("""\
        # Flask
        flask
        werkzeug
        requests
        # Server
        gunicorn==22.0.0
        # Monitoring
        sentry-sdk[Flask]
        # Core
        pydantic>=2.0.0
        PyYAML>=6.0.1
    """)
    (project_dir / "requirements.txt").write_text(content)


def _write_capability_yaml(spec: ConnectorSpec, project_dir: Path) -> None:
    data: dict = {
        "app": {
            "name": spec.app_name.replace(" Connector", ""),
            "slug": spec.app_type,
            "description": f"Connector for {spec.app_name.replace(' Connector', '')}",
            "auth": {
                "type": spec.auth.type,
                "scopes": spec.auth.scopes,
            },
        },
        "actions": [
            {
                "name": a.name,
                "category": a.category,
                "description": a.description,
                "required_fields": [
                    {"name": f.name, "type": f.type, "description": f.description}
                    for f in a.required_fields
                ],
            }
            for a in spec.actions
        ],
        "triggers": [
            {
                "name": t.name,
                "event": t.event,
                "description": t.description,
            }
            for t in spec.triggers
        ],
    }
    (project_dir / "capability.yaml").write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False)
    )


# ---------------------------------------------------------------------------
# Deployment files
# ---------------------------------------------------------------------------

def _write_deployment_files(spec: ConnectorSpec, project_dir: Path) -> None:
    config_dir = project_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / "Dockerfile").write_text(textwrap.dedent("""\
        FROM python:3.11-slim
        ARG ENVIRONMENT

        WORKDIR /usr/src/app

        RUN pip install --upgrade pip

        RUN apt-get update && \\
            apt-get install -y git curl && \\
            rm -rf /var/lib/apt/lists/*

        RUN pip install git+https://github.com/stacksyncdata/workflows-cdk.git@prod

        COPY requirements.txt ./
        RUN pip3 install -r requirements.txt

        COPY . .

        EXPOSE 8080

        RUN chmod +x ./entrypoint.sh

        ENTRYPOINT ["sh", "entrypoint.sh"]
    """))

    (config_dir / "Dockerfile.dev").write_text(textwrap.dedent("""\
        FROM python:3.11-slim

        WORKDIR /usr/src/app

        RUN apt-get update && \\
            apt-get install -y git curl && \\
            rm -rf /var/lib/apt/lists/*

        RUN pip install --upgrade pip

        RUN pip install git+https://github.com/stacksyncdata/workflows-cdk.git@prod

        COPY requirements.txt ./
        RUN pip3 install -r requirements.txt

        COPY . .

        RUN chmod +x ./config/entrypoint.sh

        EXPOSE 8080

        ENTRYPOINT ["sh", "./config/entrypoint.sh"]
    """))

    (config_dir / "entrypoint.sh").write_text(
        "exec gunicorn --config /usr/src/app/config/gunicorn_config.py main:app\n"
    )

    (config_dir / "gunicorn_config.py").write_text(textwrap.dedent("""\
        bind = "0.0.0.0:8080"
        accesslog = "-"
        errorlog = "-"
        capture_output = True
        enable_stdio_inheritance = True

        workers = 2
        threads = 1
        timeout = 360
    """))

    port = DEFAULT_PORT
    (project_dir / "run_dev.sh").write_text(textwrap.dedent(f"""\
        #!/bin/bash

        REBUILD=false
        for arg in "$@"; do
          if [ "$arg" == "--build" ]; then
            REBUILD=true
          fi
        done

        echo ""
        echo "Stacksync App Connector"
        echo "Documentation: https://docs.stacksync.com/workflows/app-connector"
        echo ""

        if [ ! -d "config" ]; then
          mkdir -p config
        fi

        PORT={port}
        DOCKERFILE_PATH="config/Dockerfile.dev"
        REPO_NAME=$(basename "$PWD")
        APP_NAME="workflows-app-${{REPO_NAME}}"

        echo "Preparing ${{APP_NAME}}..."

        IMAGE_EXISTS=$(docker images -q ${{APP_NAME}} 2> /dev/null)

        if [ -z "$IMAGE_EXISTS" ] || [ "$REBUILD" == "true" ]; then
          if [ "$REBUILD" == "true" ]; then
            echo "Forcing rebuild of Docker image: ${{APP_NAME}}"
            docker build --no-cache -t ${{APP_NAME}} -f ${{DOCKERFILE_PATH}} .
          else
            echo "Docker image not found. Building: ${{APP_NAME}}"
            docker build -t ${{APP_NAME}} -f ${{DOCKERFILE_PATH}} .
          fi
        else
          echo "Docker image ${{APP_NAME}} already exists. Skipping build."
          echo "Use --build flag to force a rebuild."
        fi

        if [ $? -ne 0 ]; then
          echo "Docker build failed. Exiting..."
          exit 1
        fi

        echo "Starting container on port ${{PORT}}..."
        docker run --rm -p ${{PORT}}:8080 -it -e ENVIRONMENT=dev -e REGION=besg --name=${{APP_NAME}} -v $PWD:/usr/src/app/ ${{APP_NAME}}
    """))

    (project_dir / "run_dev.bat").write_text(textwrap.dedent(f"""\
        @echo off
        setlocal enabledelayedexpansion

        set "REBUILD=false"
        for %%a in (%*) do (
            if "%%a"=="--build" set "REBUILD=true"
        )

        echo.
        echo Stacksync App Connector
        echo Documentation: https://docs.stacksync.com/workflows/app-connector
        echo.

        if not exist "config" mkdir config

        set "PORT={port}"
        set "DOCKERFILE_PATH=config\\Dockerfile.dev"

        for %%%%I in ("%%CD%%") do set "DIRNAME=%%%%~nxI"
        set "APP_NAME=workflows-app-!DIRNAME!"

        echo Preparing !APP_NAME!...

        set "IMAGE_EXISTS="
        for /f %%%%i in ('docker images -q !APP_NAME! 2^>nul') do set "IMAGE_EXISTS=%%%%i"

        if "!IMAGE_EXISTS!"=="" (
            echo Docker image not found. Building: !APP_NAME!
            docker build -t !APP_NAME! -f !DOCKERFILE_PATH! .
        ) else if "!REBUILD!"=="true" (
            echo Forcing rebuild: !APP_NAME!
            docker build --no-cache -t !APP_NAME! -f !DOCKERFILE_PATH! .
        ) else (
            echo Docker image !APP_NAME! already exists. Use --build to rebuild.
        )

        if errorlevel 1 (
            echo Docker build failed. Exiting...
            exit /b 1
        )

        echo Starting container on port !PORT!...
        docker run --rm -p !PORT!:8080 -it -e ENVIRONMENT=dev -e REGION=besg --name=!APP_NAME! -v %%CD%%:/usr/src/app/ !APP_NAME!
    """))


# ---------------------------------------------------------------------------
# Module config
# ---------------------------------------------------------------------------

def _write_module_config(name: str, description: str, route_dir: Path) -> None:
    """Write module_config.yaml for a single module version."""
    human_name = name.replace("_", " ").title()
    config = {
        "module_settings": {
            "module_name": human_name,
            "module_description": description or f"{human_name} Module",
        }
    }
    (route_dir / "module_config.yaml").write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False)
    )


# ---------------------------------------------------------------------------
# Module Schema (Stacksync format)
# ---------------------------------------------------------------------------

_WIDGET_MAP = {
    "string": "input",
    "number": "input",
    "boolean": "checkbox",
    "object": "SelectWidget",
    "array": "input",
}


def _build_module_schema(
    fields: list[FieldSpec],
    auth: AuthSpec,
    app_type: str,
) -> dict:
    """Build a Stacksync Module Schema (v1.0.0) from field specs."""
    schema_fields: list[dict] = []

    if auth.type in ("oauth2", "api_key"):
        conn_field: dict = {
            "type": "connection",
            "id": "api_connection",
            "label": "Connection",
            "allowed_app_types": [app_type],
            "allowed_connection_management_types": ["managed"],
            "validation": {"required": True},
        }
        schema_fields.append(conn_field)

    for f in fields:
        field_def: dict = {
            "id": f.name,
            "type": f.type,
            "label": f.name.replace("_", " ").title(),
            "description": f.description,
        }
        if f.required:
            field_def["validation"] = {"required": True}

        widget = _WIDGET_MAP.get(f.type, "input")
        field_def["ui_options"] = {"ui_widget": widget}

        schema_fields.append(field_def)

    field_ids = [sf["id"] for sf in schema_fields]

    return {
        "metadata": {"workflows_module_schema_version": "1.0.0"},
        "fields": schema_fields,
        "ui_options": {"ui_order": field_ids},
    }


# ---------------------------------------------------------------------------
# Route generation
# ---------------------------------------------------------------------------

def _extract_imports(code: str) -> tuple[list[str], str]:
    """Separate import statements from implementation code.

    Returns (import_lines, remaining_code).
    """
    import_lines: list[str] = []
    body_lines: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            import_lines.append(stripped)
        else:
            body_lines.append(line)
    remaining = "\n".join(body_lines).strip()
    return import_lines, remaining


def _indent(code: str, level: int = 1) -> str:
    """Indent each line of *code* by *level* * 4 spaces."""
    prefix = "    " * level
    return "\n".join(prefix + line if line.strip() else "" for line in code.splitlines())


def _write_action_route(
    spec: ConnectorSpec,
    action: ActionSpec,
    project_dir: Path,
) -> None:
    route_dir = project_dir / MODULES_DIR / action.name / spec.version
    route_dir.mkdir(parents=True, exist_ok=True)

    all_fields = list(action.required_fields) + list(action.optional_fields)

    extra_imports: list[str] = []
    if action.implementation.strip():
        extra_imports, clean_impl = _extract_imports(action.implementation)
        execute_body = _indent(clean_impl)
    else:
        execute_body = _build_stub_body(spec, action.name, all_fields, action.category)

    route_code = _build_route_file(execute_body, extra_imports)
    (route_dir / "route.py").write_text(route_code)

    schema = _build_module_schema(all_fields, spec.auth, spec.app_type)
    (route_dir / "schema.json").write_text(json.dumps(schema, indent=2) + "\n")

    _write_module_config(action.name, action.description, route_dir)


def _write_trigger_route(
    spec: ConnectorSpec,
    trigger: TriggerSpec,
    project_dir: Path,
) -> None:
    route_dir = project_dir / MODULES_DIR / trigger.name / spec.version
    route_dir.mkdir(parents=True, exist_ok=True)

    extra_imports: list[str] = []
    if trigger.implementation.strip():
        extra_imports, clean_impl = _extract_imports(trigger.implementation)
        execute_body = _indent(clean_impl)
    else:
        execute_body = _build_trigger_stub_body(spec, trigger)

    route_code = _build_route_file(execute_body, extra_imports)
    (route_dir / "route.py").write_text(route_code)

    schema = _build_module_schema(trigger.payload_fields, spec.auth, spec.app_type)
    (route_dir / "schema.json").write_text(json.dumps(schema, indent=2) + "\n")

    _write_module_config(trigger.name, trigger.description, route_dir)


def _build_route_file(execute_body: str, extra_imports: list[str] | None = None) -> str:
    """Assemble a complete route.py with /execute, /content, and /schema."""
    base_imports = [
        "import json",
        "",
        "import requests",
        "from flask import request as flask_request",
        "from workflows_cdk import Request, Response, ManagedError",
        "from main import router",
    ]
    if extra_imports:
        already = {line.strip() for line in base_imports if line.strip()}
        for imp in extra_imports:
            if imp not in already:
                base_imports.insert(1, imp)

    import_block = "\n".join(base_imports)

    body = (
        import_block
        + "\n\n\n"
        + "@router.route(\"/execute\", methods=[\"POST\"])\n"
        + "def execute():\n"
        + "    req = Request(flask_request)\n"
        + "    data = req.data\n"
        + "    credentials = req.credentials\n"
        + "\n"
        + execute_body + "\n"
        + "\n\n"
        + "@router.route(\"/content\", methods=[\"POST\"])\n"
        + "def content():\n"
        + "    req = Request(flask_request)\n"
        + "    data = req.data\n"
        + "\n"
        + "    if not data:\n"
        + '        return Response(data={"message": "Missing request data"}, status_code=400)\n'
        + "\n"
        + '    form_data = data.get("form_data", {})\n'
        + '    content_object_names = data.get("content_object_names", [])\n'
        + "\n"
        + "    if isinstance(content_object_names, list) and content_object_names and isinstance(content_object_names[0], dict):\n"
        + '        content_object_names = [obj.get("id") for obj in content_object_names if "id" in obj]\n'
        + "\n"
        + "    content_objects = []\n"
        + "\n"
        + '    return Response(data={"content_objects": content_objects})\n'
        + "\n\n"
        + "@router.route(\"/schema\", methods=[\"POST\"])\n"
        + "def schema():\n"
        + "    req = Request(flask_request)\n"
        + '    schema_path = __file__.replace("route.py", "schema.json")\n'
        + "    with open(schema_path) as f:\n"
        + "        base_schema = json.load(f)\n"
        + "    return Response(data=base_schema)\n"
    )
    return body


def _build_stub_body(
    spec: ConnectorSpec,
    action_name: str,
    fields: list[FieldSpec],
    category: str,
) -> str:
    """Fallback stub when the LLM didn't generate implementation code."""
    lines: list[str] = []
    for f in fields:
        lines.append(f'    {f.name} = data.get("{f.name}")')

    lines.append("")
    lines.append(f'    # TODO: implement {spec.app_name} API call for "{action_name}"')
    lines.append("")

    if category == "search":
        lines.append('    return Response(data={"results": []})')
    else:
        lines.append('    return Response(data={"success": True})')

    return "\n".join(lines)


def _build_trigger_stub_body(spec: ConnectorSpec, trigger: TriggerSpec) -> str:
    lines = [
        f'    # TODO: implement polling / webhook logic for "{trigger.name}"',
        f"    # Event: {trigger.event}",
        "",
        '    return Response(data={"events": []})',
    ]
    return "\n".join(lines)
