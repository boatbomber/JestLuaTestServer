import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api_keys import api_key_manager
from app.config_manager import config as app_config
from app.dependencies import StudioManagerDep
from app.endpoints import events, results, test
from app.utils.studio_manager import managed_studio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def monitor_heartbeat(studio_manager):
    """Monitor heartbeat from plugin and restart Studio if no heartbeat for 5 seconds"""
    while True:
        try:
            await asyncio.sleep(1)  # Check every second

            # Skip monitoring if Studio isn't running
            if not studio_manager.is_running():
                logger.warning("Studio is not running, skipping heartbeat monitoring")
                continue

            # Skip if no heartbeat has been received yet (Studio just starting)
            if studio_manager._last_heartbeat is None:
                logger.warning("No heartbeat received yet, skipping heartbeat monitoring")
                continue

            # Check if heartbeat is stale (no heartbeat for 5 seconds)
            time_since_heartbeat = (datetime.now() - studio_manager._last_heartbeat).total_seconds()
            logger.debug(f"Time since heartbeat: {time_since_heartbeat:.1f}s")
            if time_since_heartbeat > 8:
                logger.warning(
                    f"No heartbeat for {time_since_heartbeat:.1f}s, restarting Studio..."
                )

                try:
                    # Force kill Studio since it's likely hung
                    await studio_manager.stop_studio(skip_graceful=True)

                    # Restart Studio
                    studio_manager._last_heartbeat = None
                    restart_success = await studio_manager.start_studio()

                    if restart_success:
                        logger.info("Studio successfully restarted due to missing heartbeat")
                    else:
                        logger.error("Failed to restart Studio after heartbeat timeout")

                except Exception as e:
                    logger.error(f"Error during Studio restart after heartbeat timeout: {e}")

        except asyncio.CancelledError:
            logger.info("Heartbeat monitoring cancelled")
            break
        except Exception as e:
            logger.error(f"Error in heartbeat monitoring: {e}")
            await asyncio.sleep(5)  # Wait before retrying


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize authentication
    if app_config.enable_auth:
        api_key_manager.load()
    else:
        logger.warning("Authentication is disabled. All endpoints are unprotected.")

    async with managed_studio() as studio_manager:
        app.state.studio_manager = studio_manager
        app.state.test_queue = asyncio.Queue()
        app.state.result_queue = asyncio.Queue()
        app.state.active_tests = {}
        app.state.rate_limiter = defaultdict(list)  # Track requests per client
        app.state.accepting_tests = True  # For graceful shutdown

        # Start heartbeat monitoring task
        heartbeat_task = asyncio.create_task(monitor_heartbeat(studio_manager))

        yield

        logger.info("Shutting down server...")

        # Stop accepting new tests
        app.state.accepting_tests = False
        logger.info("Stopped accepting new tests")

        # Cancel heartbeat monitoring
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

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
