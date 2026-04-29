from __future__ import annotations

import modal

from proteina_complexa.config import DEFAULT_GPU, SCALEDOWN_WINDOW_SECONDS, TIMEOUT_SECONDS
from proteina_complexa.http_server import create_app
from proteina_complexa.modal_resources import (
    api_secret,
    app,
    data_volume,
    hf_secret,
    image,
    model_volume,
    runs_volume,
)
from proteina_complexa.runtime import ensure_model_weights


@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={
        "/models": model_volume,
        "/data": data_volume,
        "/runs": runs_volume,
    },
    secrets=[api_secret, hf_secret],
    min_containers=0,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    timeout=TIMEOUT_SECONDS,
)
@modal.asgi_app()
def fastapi_app():
    ensure_model_weights()
    return create_app()

