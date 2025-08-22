"""Authentication middleware for Bearer token validation"""

import logging
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api_keys import api_key_manager
from app.config_manager import config as app_config

logger = logging.getLogger(__name__)

bearer_auth = HTTPBearer(auto_error=False)


class SessionTokenAuth:
    """Bearer token authentication handler for internal endpoints"""

    def __init__(self):
        self._session_token: str | None = None
        self._enabled = app_config.enable_auth

    def get_session_token(self) -> str:
        """Get or generate a secure token for internal plugin communication"""
        if not self._session_token:
            self._session_token = secrets.token_urlsafe(32)
        return self._session_token

    async def verify_session_token(
        self,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    ) -> bool:
        """Verify that the provided token matches the session token"""
        # If auth is disabled, allow all requests
        if not self._enabled:
            return True

        if not self._session_token:
            # We should never reach this point!
            logger.error("Authentication is enabled yet no session token exists!")
            return False

        if not credentials:
            raise HTTPException(
                status_code=401,
                detail="Authorization header required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.info(credentials.__class__.__name__)
        logger.info(credentials)

        if not credentials.scheme.lower() == "bearer":
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization scheme",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if credentials.credentials != self._session_token:
            raise HTTPException(
                status_code=403,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return True


class APIKeyAuth:
    """API key authentication handler for remote worker access"""

    def __init__(self):
        self._enabled = app_config.enable_auth

    async def verify_api_key(self, x_api_key: str = Header(None)) -> bool:
        """Verify API key for remote worker access to /test endpoint"""
        # If auth is disabled, allow all requests
        if not self._enabled:
            return True

        # Check if API key is provided
        if not x_api_key:
            raise HTTPException(
                status_code=401,
                detail="X-API-Key header required",
            )

        # Validate the API key
        if not api_key_manager.is_valid_key(x_api_key):
            raise HTTPException(
                status_code=403,
                detail="Invalid API key",
            )

        return True


internal_auth = SessionTokenAuth()
external_auth = APIKeyAuth()

# Export dependencies
InternalAuthDep = Annotated[bool, Depends(internal_auth.verify_session_token)]
ExternalAuthDep = Annotated[bool, Depends(external_auth.verify_api_key)]
