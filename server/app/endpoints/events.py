import asyncio
import base64
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter()

CHUNK_SIZE = 8192


async def event_generator(request: Request) -> AsyncGenerator:
    logger.info("Client connected to SSE endpoint")
    
    try:
        while True:
            if await request.is_disconnected():
                logger.info("Client disconnected from SSE")
                break
            
            try:
                test_data = await asyncio.wait_for(
                    request.app.state.test_queue.get(), 
                    timeout=1.0
                )
                
                test_id = test_data["test_id"]
                rbxm_data = test_data["data"]
                
                logger.info(f"Sending test {test_id} to plugin")
                
                yield {
                    "event": "test_start",
                    "data": json.dumps({
                        "test_id": test_id,
                        "total_size": len(rbxm_data),
                    }),
                }
                
                for i in range(0, len(rbxm_data), CHUNK_SIZE):
                    chunk = rbxm_data[i:i + CHUNK_SIZE]
                    chunk_b64 = base64.b64encode(chunk).decode("utf-8")
                    
                    yield {
                        "event": "test_chunk",
                        "data": json.dumps({
                            "test_id": test_id,
                            "chunk": chunk_b64,
                            "offset": i,
                            "size": len(chunk),
                        }),
                    }
                    
                    await asyncio.sleep(0.01)
                
                yield {
                    "event": "test_end",
                    "data": json.dumps({
                        "test_id": test_id,
                    }),
                }
                
            except asyncio.TimeoutError:
                yield {
                    "event": "ping",
                    "data": "keep-alive",
                }
                
    except asyncio.CancelledError:
        logger.info("SSE connection cancelled")
        raise
    except Exception as e:
        logger.error(f"Error in SSE stream: {e}")
        raise


@router.get("/_events")
async def events_stream(request: Request):
    return EventSourceResponse(event_generator(request))