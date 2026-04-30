from __future__ import annotations

import modal

from julia_agent.main import app as fastapi_app

image = modal.Image.debian_slim(python_version="3.11").pip_install_from_pyproject(
    "pyproject.toml"
).add_local_dir(
    "julia_agent",
    remote_path="/root/julia_agent",
)
app = modal.App("julia-agent-worker", image=image)
env_secret = modal.Secret.from_dotenv(__file__)


@app.function(secrets=[env_secret])
@modal.asgi_app()
def web():
    return fastapi_app
