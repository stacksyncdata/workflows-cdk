# Workflows CDK Core Design Document

## Current State Analysis

### Core Components

- `app.py`: Flask application factory and configuration
- `router.py`: Route management and directory-based versioning
- `decorators.py`: Route decorator (@module_route)
- `request.py`: Request wrapper with intellisense support
- `responses.py`: Standardized Response formatting
- `errors.py`: Error management
- `types.py`: Type definitions

### Current Issues

1. Code Organization

   - Need clearer directory-based routing
   - Version handling needs standardization
   - Response formatting inconsistencies

2. Developer Experience
   - Improve intellisense for Request object
   - Standardize Response.success usage
   - Simplify route declarations

## Proposed Architecture

### 1. Directory-Based Routing

```
routes/
  send_message_slack_action/
    v1/
      route.py         # Handles /send_message_slack_action/v1/*
    v2/
      route.py         # Handles /send_message_slack_action/v2/*
  get_user_info/
    v1/
      route.py         # Handles /get_user_info/v1/*
```

### 2. Route Definition Pattern

```python
# routes/send_message_slack_action/v1/route.py

from workflows_cdk import module_route, Request, Response

@module_route("/schema")  # Results in /send_message_slack_action/v1/schema
def get_schema(request: Request):
    """Get module schema."""
    return Response.success(data={"schema": ...})

@module_route("/execute")  # Results in /send_message_slack_action/v1/execute
def execute(request: Request):
    """Execute action."""
    data = request.json  # Full intellisense support
    return Response.success(data={"executed": True})

# Version override example (rare case)
@module_route("/special", version="v2")
def special(request: Request):
    """Override version from directory structure."""
    return Response.success(data={"version": "v2"})
```

### 3. Core Components Integration

#### Application Factory

```python
def create_app(
    name: str = None,
    config: dict = None
) -> Flask:
    """
    Creates Flask application with automatic:
    - Route registration from directory structure
    - Version handling from directories
    - Error handling
    - Response formatting
    """
    app = Flask(name)
    register_routes_from_directory(app, "routes")
    setup_error_handlers(app)
    return app
```

#### Enhanced Module Route

```python
def module_route(
    route: str,
    methods: List[str] = ["POST"],  # POST by default
    version: Optional[str] = None   # Defaults to directory version
):
    """
    Route decorator that:
    - Uses directory structure for versioning
    - Allows version override
    - Defaults to POST method
    - Enforces Response.success usage
    - Provides Request type hints
    """
    def decorator(func: Callable[[Request], Any]):
        # Implementation
        pass
    return decorator
```

### 4. Request/Response Pattern

```python
class Request:
    """Request wrapper with full intellisense."""
    @property
    def json(self) -> Dict[str, Any]: ...
    @property
    def args(self) -> Dict[str, str]: ...
    @property
    def headers(self) -> Dict[str, str]: ...
    @property
    def files(self) -> Dict[str, FileStorage]: ...

class Response:
    """Standardized response formatting."""
    @staticmethod
    def success(
        data: Any = None,
        message: str = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]: ...
```

## Implementation Plan

### Phase 1: Directory Structure

1. Route Organization

   - Implement directory-based routing
   - Auto-version detection
   - Module categorization

2. Request/Response
   - Enhance Request type hints
   - Enforce Response.success usage
   - Improve error handling

### Phase 2: Developer Experience

1. Tooling

   - CLI for route scaffolding
   - Route testing utilities
   - Documentation generation

2. Type Safety
   - Request/Response type checking
   - Route parameter validation
   - Error type definitions

## Usage Examples

### 1. Standard Module Route

```python
# routes/send_message/v1/route.py
from workflows_cdk import module_route, Request, Response

@module_route("/execute")  # /send_message/v1/execute
def execute(request: Request):
    message = request.json["message"]  # Intellisense support
    return Response.success(data={"sent": True})
```

### 2. Multiple Endpoints

```python
# routes/user_management/v1/route.py
@module_route("/create")  # POST /user_management/v1/create
def create(request: Request):
    return Response.success(data={"created": True})

@module_route("/list", methods=["GET"])  # GET /user_management/v1/list
def list_users(request: Request):
    return Response.success(data={"users": []})
```

### 3. Schema Endpoints

```python
# Common pattern for module schema endpoints
@module_route("/schema")  # POST /module_name/v1/schema
def get_schema(request: Request):
    return Response.success(data={"schema": get_module_schema()})

@module_route("/content")  # POST /module_name/v1/content
def get_content(request: Request):
    return Response.success(data={"content": get_module_content()})
```

## Testing Strategy

1. Route Testing

   - Directory structure validation
   - Version resolution
   - Endpoint accessibility

2. Request/Response
   - Type validation
   - Response format
   - Error handling

## Migration Guide

1. Directory Structure:

```
routes/
  module_name/
    v1/
      route.py    # All endpoints for this version
    v2/
      route.py    # New version endpoints
```

2. Route Updates:

```python
# Before
@app.route("/api/v1/action")
def action():
    return {"status": "success"}

# After
@module_route("/action")  # Version from directory
def action(request: Request):
    return Response.success(data={"status": "success"})
```

## Future Enhancements

1. Developer Experience

   - Route generation CLI
   - OpenAPI documentation
   - Testing utilities

2. Performance

   - Route caching
   - Response optimization
   - Request validation

3. Monitoring
   - Request timing
   - Error tracking
   - Usage analytics
