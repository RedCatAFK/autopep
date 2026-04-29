from __future__ import annotations

import modal

from protein_scoring_server.server import BatchScoringService, create_app


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "build-essential",
        "curl",
        "git",
        "libgomp1",
        "libopenblas-dev",
    )
    .pip_install_from_requirements("requirements.txt")
    .env(
        {
            "API_KEY": "password123",
            "APP_VERSION": "prodigy-command-order-20260429-1538",
            "DSCRIPT_MODEL": "samsl/topsy_turvy_human_v1",
        }
    )
    .add_local_python_source("protein_scoring_server")
)

app = modal.App("protein-interaction-scoring")


@app.cls(
    image=image,
    gpu="T4",
    timeout=15 * 60,
    startup_timeout=15 * 60,
    scaledown_window=10 * 60,
)
class ProteinScoringService:
    @modal.enter()
    def load(self) -> None:
        self.service = BatchScoringService()
        self.service.load()

    @modal.asgi_app()
    def api(self):
        return create_app(service=self.service, load_on_startup=False)
