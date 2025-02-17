"""
Centralized Sentry error handling for the Workflows CDK.
"""

import os
import traceback
from typing import Any, Dict, Optional
from flask import Flask, request, current_app
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

def init_sentry(app: Flask, dsn: Optional[str] = None) -> None:
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
        include_local_variables=True,
        include_source_context=True,
        attach_stacktrace=True,
        profiles_sample_rate=1.0
    )
    app.logger.info("Sentry initialized successfully")
