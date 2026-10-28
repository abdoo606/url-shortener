"""HTTP layer. Business rules live in urls.py and store.py; this file only maps them."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .store import LinkStore
from .urls import UrlRejected, is_valid_code, normalise


class ShortenRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    code: str | None = Field(default=None, min_length=4, max_length=16)


class ShortenResponse(BaseModel):
    code: str
    short_url: str
    url: str


def create_app(store: LinkStore | None = None, *, base_url: str = "http://testserver") -> FastAPI:
    app = FastAPI(title="shortener", version="1.0.0")
    app.state.store = store or LinkStore()
    app.state.base_url = base_url

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/links", status_code=status.HTTP_201_CREATED, response_model=ShortenResponse)
    def shorten(payload: ShortenRequest) -> ShortenResponse:
        try:
            url = normalise(payload.url)
        except UrlRejected as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        if payload.code and not is_valid_code(payload.code):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid or reserved code")
        try:
            link = app.state.store.create(url, code=payload.code)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return ShortenResponse(
            code=link.code, short_url=f"{app.state.base_url}/{link.code}", url=link.url
        )

    @app.get("/api/links/{code}")
    def details(code: str) -> dict[str, object]:
        stats = app.state.store.stats(code)
        if stats is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown code")
        return stats

    @app.delete("/api/links/{code}", status_code=status.HTTP_204_NO_CONTENT)
    def remove(code: str) -> None:
        if not app.state.store.delete(code):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown code")

    @app.get("/api/top")
    def top(limit: int = 10) -> list[dict[str, object]]:
        limit = max(1, min(limit, 100))
        return [
            {"code": link.code, "url": link.url, "clicks": link.clicks}
            for link in app.state.store.top(limit)
        ]

    @app.get("/{code}")
    def follow(code: str, request: Request) -> RedirectResponse:
        link = app.state.store.get(code)
        if link is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown code")
        app.state.store.record_visit(
            code,
            referrer=request.headers.get("referer"),
            user_agent=request.headers.get("user-agent"),
        )
        # 302 not 301: a permanent redirect would be cached and hide future analytics.
        return RedirectResponse(link.url, status_code=status.HTTP_302_FOUND)

    return app
