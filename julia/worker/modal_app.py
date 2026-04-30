from __future__ import annotations

import modal

from julia_agent.main import app as fastapi_app

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_pyproject("pyproject.toml")
    .add_local_dir("julia_agent", remote_path="/root/julia_agent")
)

app = modal.App("julia-agent-worker", image=image)
env_secret = modal.Secret.from_dotenv(__file__)

# Long agent runs (5–30 minutes) require generous container timeouts so the
# background task started by /runs/start has time to finish. Concurrent inputs
# let one container serve multiple WebSocket subscribers and concurrent runs.
@app.function(
    secrets=[env_secret],
    timeout=60 * 60,
    scaledown_window=60 * 5,
)
@modal.concurrent(max_inputs=64)
@modal.asgi_app()
def web():
    return fastapi_app
