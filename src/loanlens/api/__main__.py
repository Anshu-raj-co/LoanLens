"""``python -m loanlens.api``: serve the API with uvicorn.

Host and port come from ``LOANLENS_API_HOST`` (default 127.0.0.1, this machine only) and
``LOANLENS_API_PORT`` (default 8000).
"""

import os

import uvicorn

uvicorn.run(
    "loanlens.api.app:app",
    host=os.environ.get("LOANLENS_API_HOST", "127.0.0.1"),
    port=int(os.environ.get("LOANLENS_API_PORT", "8000")),
    log_level="warning",
    access_log=False,  # uvicorn access lines contain client addresses; the API logs its own
)
