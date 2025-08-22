import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config_manager import config as app_config
from app.dependencies import StudioManagerDep
from app.endpoints import events, results, test
from app.utils.studio_manager import managed_studio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with managed_studio() as studio_manager:
        app.state.studio_manager = studio_manager
        app.state.test_queue = asyncio.Queue()
        app.state.result_queue = asyncio.Queue()
        app.state.active_tests = {}
        app.state.rate_limiter = defaultdict(list)  # Track requests per client
        app.state.accepting_tests = True  # For graceful shutdown

        yield

        logger.info("Shutting down server...")

        # Stop accepting new tests
        app.state.accepting_tests = False
        logger.info("Stopped accepting new tests")

        # Wait for active tests to complete (with timeout)
        max_wait = app_config.shutdown_timeout
        wait_interval = 0.5
        elapsed = 0

        while app.state.active_tests and elapsed < max_wait:
            active_count = len(app.state.active_tests)
            logger.info(f"Waiting for {active_count} active test(s) to complete...")
            await asyncio.sleep(wait_interval)
            elapsed += wait_interval

        if app.state.active_tests:
            logger.warning(
                f"Force stopping with {len(app.state.active_tests)} test(s) still active"
            )

        logger.info("Cleanup complete")


app = FastAPI(
    title="Jest Lua Test Server",
    description="Server for running Jest Lua tests in Roblox Studio",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(test.router)
app.include_router(events.router)
app.include_router(results.router)


@app.get("/health")
async def health_check(studio_manager: StudioManagerDep):
    health_status = studio_manager.is_healthy()
    all_healthy = all(health_status.values())

    return {"status": "healthy" if all_healthy else "degraded", **health_status}
