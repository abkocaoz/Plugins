from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


async def require_dev_token(
    x_api_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.auth_mode in {"open", "none", "disabled"}:
        return
    if settings.auth_mode == "dev":
        if x_api_token == settings.dev_api_token:
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Token (dev auth)",
        )
    raise HTTPException(status_code=501, detail=f"auth_mode={settings.auth_mode} not implemented")
