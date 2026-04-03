# Workflows CDK

A powerful CDK (Connector Development Kit) for building Stacksync Workflows Connectors with Python and Flask.

## Features

- 🚀 Automatic route discovery and registration file based (like in Next.js!)
- 🔒 Built-in error handling and Sentry integration
- 📦 Standardized request/response handling
- 🛠️ Error management with standardized error handling
- 🔄 Environment-aware configuration
- 🤖 AI-powered connector scaffolding via CLI (OpenAI or Anthropic)
- 📚 Built-in capability registry for Slack, Stripe, HubSpot, Salesforce, OpenAI, PostgreSQL

## Installation

```bash
pip install workflows-cdk
```

## Configuration

On first run, the CLI will ask you to pick a provider and paste your API key:

```
$ workflows create "Slack connector"

╭─ Welcome to Workflows CDK ──────────────────────────╮
│ No API key found. Let's set one up.                  │
│ You can reconfigure anytime with workflows setup.    │
╰──────────────────────────────────────────────────────╯

Which AI provider? [anthropic/openai] (anthropic):
Paste your ANTHROPIC_API_KEY (sk-ant-...): sk-ant-xxxxx

Done! ANTHROPIC_API_KEY saved to .env
```

You can also configure manually:

```bash
# Interactive setup / reconfigure
workflows setup

# Or set keys directly via .env
echo 'ANTHROPIC_API_KEY=sk-ant-your-key-here' > .env

# Or export in your shell
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Both `.env` and environment variables work. Environment variables take priority.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | One of these | Anthropic API key — uses Claude Sonnet 4.6 by default |
| `OPENAI_API_KEY` | One of these | OpenAI API key — uses GPT-5 Nano by default |
| `WORKFLOWS_AI_PROVIDER` | No | Force a provider when both keys are set: `anthropic` or `openai` |
| `WORKFLOWS_AI_MODEL` | No | Override the default model (default: `claude-sonnet-4-6` or `gpt-5-nano`) |
| `ENVIRONMENT` | No | Runtime environment: `dev`, `stage`, or `prod` |

No API key? Use `--no-ai` to create connectors via built-in template matching instead.

## Quick Start

### AI-powered (recommended)

Create a connector in one command:

```bash
workflows create "Slack connector: send messages, list channels"
```

A complete project appears in `./slack-connector/` with working Flask routes, schemas, and config -- ready to run with `python main.py`.

More examples:

```bash
# Preview without writing files
workflows create "HubSpot CRM: create contacts, search, manage deals" --dry-run

# Template matching only (no API key needed)
workflows create "Slack: send messages, list channels" --no-ai

# Specify output directory
workflows create "PostgreSQL: query, insert, search rows" -o ./connectors

# List available capabilities
workflows list

# Inspect a specific app
workflows inspect slack
```

### Manual setup

1. Create a new project directory:

```bash
mkdir my-workflow-connector
cd my-workflow-connector
```

2. Install the required dependencies:

```bash
pip install workflows-cdk flask pyyaml
```

3. Create the basic project structure:

```
my-workflow-connector/
├── main.py
├── app_config.yaml
├── requirements.txt
└── routes/
    └── hello/
        └── v1/
            └── route.py
```

4. Set up your `app_config.yaml`:

```yaml
app_settings:
  app_type: "example"
  app_name: "My Workflow Connector"
  app_description: "A simple workflow connector"
  sentry_dsn: "your-sentry-dsn" # Optional
  cors_origins: ["*"]
  routes_directory: "routes"
  debug: true
  host: "0.0.0.0"
  port: 2005
```

5. Create your `main.py`:

```python
from flask import Flask
from workflows_cdk import Router

# Create Flask app
app = Flask("my-workflow-connector")

# Initialize router with configuration
router = Router(app)

# Run the app
if __name__ == "__main__":
    router.run_app(app)
```

6. Create your first route in `routes/send_message/v1/route.py`:

```python
from workflows_cdk import Request, Response, ManagedError
from main import router

@router.route("/execute", methods=["POST"])
def execute():
    """Execute the send message action."""
    request = Request(flask_request)
    data = request.data

    name = data.get("name", "World")
    return Response.success(data={
        "message": f"Hello, {name}!"
    })
```

## Core Components

### Router

The `Router` class is the heart of the CDK, providing:

- Automatic route discovery based on file system structure
- Built-in error handling and Sentry integration
- CORS configuration
- Health check endpoints
- API documentation

### Request

The `Request` class wraps Flask's request object, providing:

- Easy access to request data and credentials
- Automatic JSON parsing
- Type-safe access to common properties

### Response

The `Response` class provides standardized response formatting:

- Success responses with optional metadata
- Error responses with appropriate status codes
- Environment-aware error details
- Sentry integration

### ManagedError

The `ManagedError` class provides structured error handling:

- Type-safe error creation
- Automatic Sentry reporting
- Environment-aware error details
- Common error types (validation, not found, unauthorized, etc.)

## Project Structure

Recommended project structure for a workflow connector:

```
my-workflow-connector/
├── main.py                 # Application entry point
├── app_config.yaml         # Application configuration
├── requirements.txt        # Python dependencies
├── README.md              # Project documentation
├── Dockerfile             # Container configuration
├── .env                   # Environment variables
└── routes/                # Route modules
    └── action_name/       # Group routes by action
        ├── v1/            # Version 1 of the action
        │   ├── route.py   # Route implementation
        │   └── schema.json # JSON Schema for validation
        └── v2/            # Version 2 of the action
            ├── route.py
            └── schema.json
```

## Error Handling

The CDK provides comprehensive error handling:

```python
from workflows_cdk import ManagedError

# Validation error
raise ManagedError.validation_error(
    error="Invalid input",
    data={"field": "email"}
)

# Not found error
raise ManagedError.not_found(
    resource="User",
    identifier="123"
)

# Authorization error
raise ManagedError.unauthorized(
    message="Invalid API key"
)

# Server error
raise ManagedError.server_error(
    error="Database connection failed"
)
```

## Response Formatting

Standardized response formatting:

```python
from workflows_cdk import Response

# Success response
return Response.success(
    data={"result": "ok"},
    message="Operation completed",
    metadata={"timestamp": "2024-02-17"}
)

# Error response
return Response.error(
    error="Something went wrong",
    status_code=400
)
```

## License

This project is licensed under the Stacksync Connector License (SCL) v1.0.
