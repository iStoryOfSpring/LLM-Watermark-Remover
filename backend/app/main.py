from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="LLM Watermark Remover",
        version="0.1.0",
        description="Local-first constrained lexical rewrite service",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin, "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    frontend_dist = settings.resource_root / "frontend" / "dist"
    if frontend_dist.exists():
        assets = frontend_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def frontend_index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @app.get("/favicon.svg", include_in_schema=False)
        def frontend_favicon() -> FileResponse:
            return FileResponse(frontend_dist / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port, reload=False)
