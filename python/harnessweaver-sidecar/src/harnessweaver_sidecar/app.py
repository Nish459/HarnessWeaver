"""The harnessd HTTP application."""

from fastapi import FastAPI

import harnessweaver
from harnessweaver_sidecar import __version__


def create_app() -> FastAPI:
    """Build the harnessd application.

    Returns:
        A FastAPI app exposing the ``/v1`` API.
    """
    app = FastAPI(title="harnessd", version=__version__)

    @app.get("/v1/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok", "harnessd": __version__, "harnessweaver": harnessweaver.__version__}

    return app
