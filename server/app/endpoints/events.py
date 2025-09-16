import asyncio
import base64
import json
import logging
from collections.abc import AsyncGenerator
from math import ceil

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.auth import InternalAuthDep
from app.config_manager import config as app_config
from app.dependencies import StudioManagerDep

logger = logging.getLogger(__name__)

router = APIRouter()


async def _chunk_data_async(data: str, chunk_size: int):
    """Async generator for chunking data with backpressure support"""
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]
        # Allow other tasks to run
        if i % (chunk_size * 10) == 0:  # Yield control every 10 chunks
            await asyncio.sleep(0)


async def event_generator(
    request: Request,
    studio_manager: StudioManagerDep,
) -> AsyncGenerator:
    logger.info("Client connected to SSE endpoint")
    current_test_data = None

    studio_manager._plugin_connections.add(request)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("Client disconnected from SSE")
                studio_manager._plugin_connections.remove(request)
                # Put test data back if we have any that wasn't fully sent
                if current_test_data is not None:
                    logger.warning(
                        f"Client disconnected during test {current_test_data['test_id']}, re-queueing"
                    )
                    await request.app.state.test_queue.put(current_test_data)
                break

            try:
                test_data = await asyncio.wait_for(request.app.state.test_queue.get(), timeout=15.0)
                current_test_data = test_data  # Track the current test being processed

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

                # Use async generator for better backpressure handling
                chunk_idx = 0
                final_chunk_idx = ceil(len(b64_rbxm) / app_config.chunk_size)
                async for chunk in _chunk_data_async(b64_rbxm, app_config.chunk_size):
                    chunk_idx += 1

                    # Check for disconnection before sending each chunk
                    if await request.is_disconnected():
                        logger.warning(
                            f"Client disconnected during chunk streaming for test {test_id}, re-queueing"
                        )
                        studio_manager._plugin_connections.remove(request)
                        await request.app.state.test_queue.put(current_test_data)
                        current_test_data = None
                        return

                    yield {
                        "event": "test_chunk",
                        "data": json.dumps(
                            {
                                "test_id": test_id,
                                "is_final_chunk": chunk_idx == final_chunk_idx,
                                "chunk_buffer": {
                                    "m": None,
                                    "t": "buffer",
                                    "base64": chunk,
                                },
                            }
                        ),
                    }
                    await asyncio.sleep(0.1)

                # Successfully sent all data, clear the current test
                current_test_data = None

            except TimeoutError:
                # Timed out while waiting for a test to enter the queue
                # Just keep waiting until the server is shut down
                continue

    except asyncio.CancelledError:
        studio_manager._plugin_connections.remove(request)
        logger.info("SSE connection cancelled")
        # Put test data back if we have any that wasn't fully sent
        if current_test_data is not None:
            logger.warning(f"SSE cancelled during test {current_test_data['test_id']}, re-queueing")
            await request.app.state.test_queue.put(current_test_data)
        raise
    except Exception as e:
        studio_manager._plugin_connections.remove(request)
        logger.error(f"Error in SSE stream: {e}")
        # Put test data back if we have any that wasn't fully sent
        if current_test_data is not None:
            logger.warning(f"Error during test {current_test_data['test_id']}: {e}, re-queueing")
            await request.app.state.test_queue.put(current_test_data)
        raise


@router.get("/_events")
async def events_stream(
    request: Request,
    _auth: InternalAuthDep,
    studio_manager: StudioManagerDep,
):
    return EventSourceResponse(event_generator(request, studio_manager))
