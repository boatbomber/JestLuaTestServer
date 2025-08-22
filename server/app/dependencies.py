"""Dependency injection for better testability and modularity"""

from typing import Annotated

from fastapi import Depends, Request

from app.utils.plugin_manager import PluginManager
from app.utils.studio_manager import StudioManager


def get_studio_manager(request: Request) -> StudioManager:
    """Get StudioManager instance from app state"""
    if not hasattr(request.app.state, "studio_manager"):
        raise RuntimeError("StudioManager not initialized")
    return request.app.state.studio_manager


def get_plugin_manager(request: Request) -> PluginManager:
    """Get PluginManager instance from app state"""
    if not hasattr(request.app.state, "plugin_manager"):
        raise RuntimeError("PluginManager not initialized")
    return request.app.state.plugin_manager


def get_test_queue(request: Request):
    """Get test queue from app state"""
    if not hasattr(request.app.state, "test_queue"):
        raise RuntimeError("Test queue not initialized")
    return request.app.state.test_queue


def get_active_tests(request: Request) -> dict:
    """Get active tests dict from app state"""
    if not hasattr(request.app.state, "active_tests"):
        raise RuntimeError("Active tests not initialized")
    return request.app.state.active_tests


def get_rate_limiter(request: Request) -> dict:
    """Get rate limiter dict from app state"""
    if not hasattr(request.app.state, "rate_limiter"):
        # Return empty defaultdict for tests
        from collections import defaultdict

        return defaultdict(list)
    return request.app.state.rate_limiter


def get_accepting_tests(request: Request) -> bool:
    """Check if server is accepting new tests"""
    if not hasattr(request.app.state, "accepting_tests"):
        return False
    return request.app.state.accepting_tests


# Type annotations for dependency injection
StudioManagerDep = Annotated[StudioManager, Depends(get_studio_manager)]
PluginManagerDep = Annotated[PluginManager, Depends(get_plugin_manager)]
TestQueueDep = Annotated[object, Depends(get_test_queue)]
ActiveTestsDep = Annotated[dict, Depends(get_active_tests)]
RateLimiterDep = Annotated[dict, Depends(get_rate_limiter)]
AcceptingTestsDep = Annotated[bool, Depends(get_accepting_tests)]
