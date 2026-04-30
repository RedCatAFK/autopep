"""Modal image definition for the autopep-agent-runtime sandbox.

The OpenAI Agents SDK's ModalSandboxClient launches sandboxes from a
Modal app named in ModalSandboxClientOptions(app_name=...). The app
must exist (be deployed) before the agent attempts to create a session.

This module:
  1. Declares the image so it can be deployed via `modal deploy`.
  2. Exposes SANDBOX_APP_NAME for use in runner.py.

Image contents:
  * BioPython + numpy + pandas + scipy + httpx + pyyaml — so the agent's
    Shell capability can run real protein-engineering code without
    per-run pip installs.

The R2 workspace mount uses Modal's native ``ModalCloudBucketMountStrategy``
(not rclone), so we don't need rclone or fuse3 in the image.
"""

from __future__ import annotations

import modal

SANDBOX_APP_NAME = "autopep-agent-runtime"

app = modal.App(SANDBOX_APP_NAME)

sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "ca-certificates")
    .pip_install(
        "biopython>=1.84",
        "numpy>=1.26",
        "pandas>=2.2",
        "scipy>=1.13",
        "httpx>=0.27",
        "pyyaml>=6.0",
    )
)


@app.function(image=sandbox_image)
def _sandbox_warmup() -> str:
    """Health endpoint so `modal app list` shows the app as deployable."""
    return "ok"


if __name__ == "__main__":
    pass
