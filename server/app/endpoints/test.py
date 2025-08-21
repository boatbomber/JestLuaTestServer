import asyncio
import logging
import uuid

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class TestResponse(BaseModel):
    test_id: str
    status: str
    results: dict | None = None
    error: str | None = None


@router.post("/test", response_model=TestResponse)
async def run_test(
    request: Request,
    rbxm_data: bytes = Body(..., media_type="application/octet-stream"),
) -> TestResponse:
    test_id = str(uuid.uuid4())

    if not rbxm_data:
        raise HTTPException(status_code=400, detail="No rbxm data provided")

    try:
        logger.info(f"Starting test {test_id}, rbxm size: {len(rbxm_data)} bytes")

        result_future = asyncio.Future()
        request.app.state.active_tests[test_id] = {
            "data": rbxm_data,
            "future": result_future,
        }

        await request.app.state.test_queue.put(
            {
                "test_id": test_id,
                "data": rbxm_data,
            }
        )

        try:
            outcome = await asyncio.wait_for(result_future, timeout=settings.test_timeout)
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
            logger.error(f"Test {test_id} timed out")
            return TestResponse(
                test_id=test_id,
                status="timeout",
                error=f"Test execution timed out after {settings.test_timeout} seconds",
            )

    except Exception as e:
        logger.error(f"Error running test {test_id}: {e}")
        return TestResponse(
            test_id=test_id,
            status="error",
            error=str(e),
        )
    finally:
        request.app.state.active_tests.pop(test_id, None)
