"""
Default Gunicorn configuration.
"""

import multiprocessing
import os

# Server socket
bind = os.getenv("BIND", "0.0.0.0:8080")
backlog = int(os.getenv("BACKLOG", "2048"))

# Worker processes
workers = int(os.getenv("WORKERS", str(multiprocessing.cpu_count() * 2 + 1)))
worker_class = os.getenv("WORKER_CLASS", "sync")
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))
timeout = int(os.getenv("TIMEOUT", "360"))
keepalive = int(os.getenv("KEEPALIVE", "2"))

# Process naming
proc_name = os.getenv("PROC_NAME", None)
default_proc_name = "workflows"

# Logging
accesslog = os.getenv("ACCESS_LOG", "-")
errorlog = os.getenv("ERROR_LOG", "-")
loglevel = os.getenv("LOG_LEVEL", "info")

# SSL
keyfile = os.getenv("SSL_KEYFILE", None)
certfile = os.getenv("SSL_CERTFILE", None)

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL
ssl_version = os.getenv("SSL_VERSION", "TLS")
cert_reqs = os.getenv("CERT_REQS", "0")
ca_certs = os.getenv("CA_CERTS", None)
suppress_ragged_eofs = True
do_handshake_on_connect = False

# Security
limit_request_line = int(os.getenv("LIMIT_REQUEST_LINE", "4094"))
limit_request_fields = int(os.getenv("LIMIT_REQUEST_FIELDS", "100"))
limit_request_field_size = int(os.getenv("LIMIT_REQUEST_FIELD_SIZE", "8190")) 