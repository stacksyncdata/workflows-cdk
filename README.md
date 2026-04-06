# Workflows CDK

A CDK (Connector Development Kit) for building **Stacksync Workflows** connectors with **Python** and **Flask**, plus a **`workflows`** CLI for AI-assisted scaffolding and day-to-day tasks.

## Features

**Runtime (library)**

- 🚀 File-based route discovery under `src/modules/` (like the [app connector template](https://github.com/stacksyncdata/workflows-app-connector-template))
- 🔒 Built-in error handling and optional Sentry integration
- 📦 Standardized `Request` / `Response` handling
- 🔄 Environment-aware configuration via `app_config.yaml`

**CLI (`workflows` command)**

- 🤖 Generate connectors or modules from a short natural-language description (`workflows create`)
- 📋 Interactive **main menu** when you run `workflows` with no arguments
- ➕ **Update** an existing project with new modules (`create --module-only`, also from the menu)
- ✅ **Validate** a connector folder (`validate`, with path prompt in the menu)
- 🖥️ **Run locally** from the menu (`run_dev.sh` or `python main.py`)
- 🌐 **Expose with ngrok** from the menu (starts the app on the configured port when needed, then tunnel)
- 📍 **Region** from the project `.env` shown in the UI (keep Studio and workflows in the same region)
- 📖 **`workflows guide`** — short help for run, ngrok, register, test
- 🔎 **`workflows list`** / **`workflows inspect`** — browse built-in capability manifests

## Prerequisites

- **Python 3.10+**
- **Docker** — recommended for `./run_dev.sh` (same flow as the official template)
- **ngrok** — optional; install from [ngrok.com](https://ngrok.com/download) if you use menu option **Expose with ngrok**
- **Anthropic or OpenAI API key** — optional; required for AI generation (otherwise use `--no-ai` or template matching)

## Installation

```bash
pip install workflows-cdk
```

## Quick start

### 1. Create a connector

```bash
workflows create "Klaviyo connector with API key"
```

Confirm at the preview, choose overwrite/version if prompted, then open the generated folder (name is derived from your description, e.g. `klaviyo-connector`).

If you have no API key, the CLI can run **`workflows setup`** or fall back to template matching.

### 2. Run it locally

```bash
cd klaviyo-connector   # use your generated folder name
pip install -r requirements.txt
./run_dev.sh
```

Default URL: `http://localhost:2003` (change port in `app_config.yaml` if needed).

### 3. Expose and register in Stacksync

- Use **Expose with ngrok** from the post-create menu, or run: `ngrok http 2003` (use your real port).
- Copy the **HTTPS** URL into **Stacksync Developer Studio**.
- Use the **same `REGION`** in Studio and in workflows as in the project `.env` (e.g. `REGION=besg`).

If Studio says the URL already exists, start a **new** ngrok session for a new URL, or remove/edit the existing private app.

### 4. (Optional) Open the full menu anytime

```bash
workflows
```

Pick **1–8** at the prompt (enter a **path** only when the menu asks for it).

---

## Interactive main menu

Run:

```bash
workflows
```

| # | Option | What to do |
|---|--------|------------|
| **1** | Create a connector | Enter a description; same flow as `workflows create "…"` |
| **2** | Update a connector | Enter project path, then what to add → adds modules only |
| **3** | Validate a project | Enter connector root path |
| **4** | Run connector locally | Enter path → `run_dev.sh` or `python main.py` |
| **5** | Expose with ngrok | Enter path → app started if needed, then ngrok; copy the HTTPS URL |
| **6** | View documentation | Opens the custom connector guide in the browser |
| **7** | Setup AI provider | Configure Anthropic / OpenAI key (saved to `.env` in the current directory) |
| **8** | Exit | Leave the menu |

After each action, press **Enter** when asked to return to the menu.

---

## After `workflows create` — next steps menu

| # | Option | What to do |
|---|--------|------------|
| **1** | Run the connector | `run_dev.sh` or `python main.py` in the new project |
| **2** | Expose with ngrok | Same as main menu **5**, using the new project automatically |
| **3** | Open documentation | Opens Stacksync developer docs |
| **4** | Exit | Close this menu |

The panel shows your **Stacksync region** from the generated `.env`.

---

## Command reference

| Command | Use it to… |
|---------|------------|
| `workflows` | Open the interactive main menu |
| `workflows create "<description>"` | Generate a new connector (or use `-o` for parent directory) |
| `workflows create --dry-run` | Preview without writing files |
| `workflows create --no-ai` | Template matching only (no LLM) |
| `workflows create --module-only` | Add modules into an existing connector directory (`-o` = that directory) |
| `workflows validate` | Validate the current directory |
| `workflows validate -p <path>` | Validate a specific connector root |
| `workflows setup` | Configure AI provider and API key |
| `workflows list` | List built-in app slugs in the registry |
| `workflows inspect <slug>` | Show actions/triggers for one app |
| `workflows guide run` | Print how to run locally |
| `workflows guide ngrok` | Print how to expose with ngrok |
| `workflows guide register` | Print how to register in Developer Studio |
| `workflows guide test` | Print how to test in a workflow |

---

## AI configuration

Set keys in the environment or in a `.env` file in the directory where you run the CLI:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude (default when set) |
| `OPENAI_API_KEY` | OpenAI |
| `WORKFLOWS_AI_PROVIDER` | `anthropic` or `openai` if both keys are set |
| `WORKFLOWS_AI_MODEL` | Override the default model |

Or run:

```bash
workflows setup
```

---

## Generated project layout

Generated projects follow the [app connector template](https://github.com/stacksyncdata/workflows-app-connector-template) layout:

```
my-connector/
├── main.py
├── app_config.yaml
├── requirements.txt
├── README.md
├── .env
├── .gitignore
├── Dockerfile
├── entrypoint.sh
├── run_dev.sh
├── run_dev.bat
├── config/
│   ├── Dockerfile.dev
│   ├── entrypoint.sh
│   └── gunicorn_config.py
└── src/modules/
    └── <action_name>/
        └── v1/
            ├── route.py
            ├── schema.json
            └── module_config.yaml
```

---

## Writing routes

Each module’s `route.py` uses the CDK helpers. Minimal pattern:

```python
from workflows_cdk import Request, Response, ManagedError
from main import router

@router.route("/execute", methods=["POST"])
def execute():
    req = Request(flask_request)
    data = req.data
    credentials = req.credentials
    # … call your API …
    return Response(data={"result": "ok"})
```

For validation, not-found, and auth errors, use `ManagedError` helpers as in the [package examples](https://github.com/stacksyncdata/workflows-cdk/blob/prod/README.md#error-handling).

---

## Documentation & resources

- [Build a custom connector](https://docs.stacksync.com/workflow-automation/developers/build-a-custom-connector)
- [Workflows app connector](https://docs.stacksync.com/workflows/app-connector)
- [Official connector template](https://github.com/stacksyncdata/workflows-app-connector-template)
- [Stacksync docs](https://docs.stacksync.com/)

---

## License

This project is licensed under the **Stacksync Connector License (SCL) v1.0**.
