import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.endpoints import events, results, test
from app.utils.plugin_manager import PluginManager
from app.utils.studio_manager import StudioManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    plugin_manager = PluginManager()
    studio_manager = StudioManager()
    
    try:
        logger.info("Installing Roblox Studio plugin...")
        await plugin_manager.install_plugin()
        
        logger.info("Starting Roblox Studio...")
        await studio_manager.start_studio()
        
        app.state.plugin_manager = plugin_manager
        app.state.studio_manager = studio_manager
        app.state.test_queue = asyncio.Queue()
        app.state.result_queue = asyncio.Queue()
        app.state.active_tests = {}
        
        yield
        
    finally:
        logger.info("Shutting down server...")
        
        if hasattr(app.state, "studio_manager"):
            await studio_manager.stop_studio()
        
        if hasattr(app.state, "plugin_manager"):
            await plugin_manager.uninstall_plugin()
        
        logger.info("Cleanup complete")


app = FastAPI(
    title="Jest Lua Test Server",
    description="Server for running Jest Lua tests in Roblox Studio",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(test.router)
app.include_router(events.router)
app.include_router(results.router)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "studio_running": hasattr(app.state, "studio_manager") and app.state.studio_manager.is_running(),
        "plugin_installed": hasattr(app.state, "plugin_manager") and app.state.plugin_manager.is_installed(),
    }