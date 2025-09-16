import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from app.auth import ExternalAuthDep, InternalAuthDep
from app.config_manager import config as app_config
from app.dependencies import (
    AcceptingTestsDep,
    ActiveTestsDep,
    RateLimiterDep,
    StudioManagerDep,
    TestQueueDep,
)

logger = logging.getLogger(__name__)

# rbxm file header signature for validation
RBXM_SIGNATURE = b"<roblox!"

router = APIRouter()


@router.post("/_heartbeat")
async def heartbeat(studio_manager: StudioManagerDep, _auth: InternalAuthDep):
    """Heartbeat endpoint for the plugin to indicate it's alive"""
    studio_manager.update_heartbeat()
    return {"status": "alive"}


class TestResponse(BaseModel):
    test_id: str
    status: str
    results: dict | None = None
    error: str | None = None


@router.post("/test", response_model=TestResponse)
async def run_test(
    request: Request,
    accepting_tests: AcceptingTestsDep,
    rate_limiter: RateLimiterDep,
    active_tests: ActiveTestsDep,
    test_queue: TestQueueDep,
    studio_manager: StudioManagerDep,
    _auth: ExternalAuthDep,
    rbxm_data: bytes = Body(b"", media_type="application/octet-stream"),
) -> TestResponse:
    test_id = str(uuid.uuid4())

    # Check if accepting tests (for graceful shutdown)
    if not accepting_tests:
        raise HTTPException(
            status_code=503, detail="Server is shutting down, not accepting new tests"
        )

    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    now = datetime.now()
    minute_ago = now - timedelta(minutes=1)

    # Clean old requests and check rate limit
    rate_limiter[client_ip] = [ts for ts in rate_limiter[client_ip] if ts > minute_ago]

    if len(rate_limiter[client_ip]) >= app_config.max_requests_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {app_config.max_requests_per_minute} requests per minute",
        )

    rate_limiter[client_ip].append(now)

    # Input validation
    if not rbxm_data:
        raise HTTPException(status_code=400, detail="No rbxm data provided")

    # Size limit check
    if len(rbxm_data) > app_config.max_rbxm_size:
        raise HTTPException(
            status_code=413,
            detail=f"RBXM file too large. Maximum size is {app_config.max_rbxm_size // (1024 * 1024)}MB",
        )

    # Validate rbxm file header
    if not rbxm_data.startswith(RBXM_SIGNATURE):
        raise HTTPException(
            status_code=400,
            detail="Invalid RBXM file format. File must be a valid Roblox model file",
        )

    try:
        logger.info(f"Received test {test_id}, rbxm size: {len(rbxm_data)} bytes")

        result_future = asyncio.Future()
        active_tests[test_id] = {
            "data": rbxm_data,
            "future": result_future,
        }

        await test_queue.put(
            {
                "test_id": test_id,
                "data": rbxm_data,
            }
        )

        while not all(studio_manager.is_healthy().values()):
            logger.debug("Waiting for Studio to be ready before starting the timeout counter")
            await asyncio.sleep(0.1)

        try:
            outcome = await asyncio.wait_for(
                result_future, timeout=test_queue.qsize() * app_config.test_timeout
            )
            logger.info(f"Responding with outcome for test {test_id}")
            if outcome.get("success"):
                return TestResponse(
                    test_id=test_id,
                    status="completed",
                    results=outcome.get("results"),
                )
            else:
                return TestResponse(
                    test_id=test_id,
                    status="failed",
                    error=outcome.get("error"),
                )

        except TimeoutError:
            logger.error(f"Test {test_id} timed out after {app_config.test_timeout} seconds")

            # Store the rbxm blob for debugging hangs
            try:
                repro_dir = Path(__file__).parent.parent.parent.parent / "repro" / "hangs"
                repro_dir.mkdir(parents=True, exist_ok=True)
                rbxm_file = repro_dir / f"{test_id}.rbxm"

                with open(rbxm_file, "wb") as f:
                    f.write(rbxm_data)

                logger.info(f"Saved timeout rbxm to {rbxm_file} for debugging")

            except Exception as e:
                logger.error(f"Failed to save timeout rbxm for {test_id}: {e}")

            return TestResponse(
                test_id=test_id,
                status="timeout",
                error=f"Test execution timed out after {app_config.test_timeout} seconds.",
            )

    except Exception as e:
        logger.error(f"Error running test {test_id}: {e}")
        return TestResponse(
            test_id=test_id,
            status="error",
            error=str(e),
        )
    finally:
        active_tests.pop(test_id, None)
