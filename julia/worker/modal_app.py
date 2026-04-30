from __future__ import annotations

import modal

from julia_agent.main import app as fastapi_app

image = modal.Image.debian_slim(python_version="3.11").pip_install_from_pyproject(
    "pyproject.toml"
)
app = modal.App("julia-agent-worker", image=image)


@app.function()
@modal.asgi_app()
def web():
    return fastapi_app
