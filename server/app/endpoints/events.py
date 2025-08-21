import asyncio
import base64
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


async def event_generator(request: Request) -> AsyncGenerator:
    logger.info("Client connected to SSE endpoint")

    try:
        while True:
            if await request.is_disconnected():
                logger.info("Client disconnected from SSE")
                break

            try:
                test_data = await asyncio.wait_for(request.app.state.test_queue.get(), timeout=15.0)

                test_id = test_data["test_id"]
                rbxm_data = test_data["data"]
                b64_rbxm = base64.b64encode(rbxm_data).decode("utf-8")

                logger.info(f"Sending test {test_id} to plugin")

                yield {
                    "event": "test_start",
                    "data": json.dumps(
                        {
                            "test_id": test_id,
                            "total_size": len(b64_rbxm),
                        }
                    ),
                }

                for i in range(0, len(b64_rbxm), settings.chunk_size):
                    chunk = b64_rbxm[i : i + settings.chunk_size]

                    yield {
                        "event": "test_chunk",
                        "data": json.dumps(
                            {
                                "test_id": test_id,
                                "chunk_buffer": {
                                    "m": None,
                                    "t": "buffer",
                                    "base64": chunk,
                                },
                            }
                        ),
                    }

                    await asyncio.sleep(1 / 60)

                yield {
                    "event": "test_end",
                    "data": json.dumps(
                        {
                            "test_id": test_id,
                        }
                    ),
                }

            except TimeoutError:
                # Timed out while waiting for a test to enter the queue
                # Just keep waiting until the server is shut down
                continue

    except asyncio.CancelledError:
        logger.info("SSE connection cancelled")
        raise
    except Exception as e:
        logger.error(f"Error in SSE stream: {e}")
        raise


@router.get("/_events")
async def events_stream(request: Request):
    return EventSourceResponse(event_generator(request))
