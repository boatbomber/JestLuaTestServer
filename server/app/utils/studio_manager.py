import asyncio
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from app.config_manager import config as app_config
from app.utils.fflag_manager import managed_fflags
from app.utils.plugin_manager import managed_plugin

logger = logging.getLogger(__name__)


class StudioManager:
    """Manages Roblox Studio process lifecycle for running tests"""

    def __init__(self):
        # Process management
        self.process: subprocess.Popen | None = None

        # Component managers
        self.plugin_manager = None  # Set by managed_studio context
        self.fflag_manager = None  # Set by managed_studio context

        # Paths
        self.unit_tests_place_dir = (Path(__file__).parent / "unit_tests_place").resolve()
        self.built_unit_tests_placefile: Path | None = None

        # Studio paths
        self.studio_dir = Path.home() / "AppData" / "Local" / "Roblox Studio"
        self.studio_path = self._find_studio_executable()

    def _find_studio_executable(self) -> Path:
        """Find Roblox Studio executable path"""
        default_path = self.studio_dir / "RobloxStudioBeta.exe"

        # Check default location first
        if default_path.exists():
            return default_path

        # Try registry lookup (Windows only)
        registry_path = self._find_studio_from_registry()
        if registry_path:
            return registry_path

        # Try alternative locations
        alt_paths = [
            Path.home() / "AppData" / "Local" / "Roblox" / "Versions" / "RobloxStudioBeta.exe",
            Path("C:/Program Files/Roblox/RobloxStudioBeta.exe"),
            Path("C:/Program Files (x86)/Roblox/RobloxStudioBeta.exe"),
        ]

        for path in alt_paths:
            if path.exists():
                logger.debug(f"Found Studio at alternative location: {path}")
                return path

        # Return default path even if not found (will error later with clear message)
        return default_path

    def _find_studio_from_registry(self) -> Path | None:
        """Try to find Studio path from Windows registry"""
        if sys.platform != "win32":
            return None

        try:
            import winreg

            # Try current user registry
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\ROBLOX Corporation\Environments\roblox-studio",
                )
                studio_exe, _ = winreg.QueryValueEx(key, "clientExe")
                winreg.CloseKey(key)
                studio_exe = Path(studio_exe)
                if studio_exe.exists():
                    logger.debug(f"Found Studio via registry (HKCU): {studio_exe}")
                    return studio_exe
            except (FileNotFoundError, OSError):
                pass

        except ImportError:
            logger.debug("winreg module not available")
        except Exception as e:
            logger.debug(f"Registry lookup failed: {e}")

        return None

    def _build_placefile(self) -> bool:
        """Build the test place file using Rojo"""
        # Install dependencies if needed
        if not (self.unit_tests_place_dir / "DevPackages").exists():
            logger.info("Installing Wally dependencies...")
            try:
                subprocess.check_output(
                    ["wally", "install"], stderr=subprocess.STDOUT, cwd=self.unit_tests_place_dir
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Wally install failed: {e}")
                return False

        # Build place file
        try:
            subprocess.check_output(
                ["rojo", "build", "-o", "build.rbxl"], cwd=self.unit_tests_place_dir
            )
            self.built_unit_tests_placefile = (self.unit_tests_place_dir / "build.rbxl").resolve()
            logger.info(f"Built place file: {self.built_unit_tests_placefile}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Rojo build failed: {e}")
            return False

    def _clean_lock_file(self) -> None:
        """Remove any stale lock files from previous sessions"""
        if not self.built_unit_tests_placefile:
            return

        lock_file_path = Path(str(self.built_unit_tests_placefile) + ".lock")
        if lock_file_path.exists():
            logger.debug(f"Removing stale lock file: {lock_file_path}")
            try:
                lock_file_path.unlink()
                logger.debug("Lock file removed successfully")
            except Exception as e:
                logger.warning(f"Failed to clean up stale lock file: {e}")

    async def _launch_studio_process(self) -> bool:
        """Launch the Studio process with appropriate settings"""
        cmd = [
            str(self.studio_path),
            "-localPlaceFile",
            str(self.built_unit_tests_placefile),
        ]

        logger.info(f"Starting Roblox Studio: {' '.join(cmd)}")

        # Platform-specific process creation
        if sys.platform == "win32":
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

        logger.debug(f"Studio process created with PID: {self.process.pid}")
        return True

    async def _verify_studio_startup(self) -> bool:
        """Verify that Studio started successfully"""
        # Check immediate startup
        await asyncio.sleep(0.1)
        if self.process.poll() is not None:
            logger.error(f"Studio process died immediately with return code: {self.process.poll()}")
            stdout, stderr = self.process.communicate()
            if stdout:
                logger.error(f"STDOUT: {stdout}")
            if stderr:
                logger.error(f"STDERR: {stderr}")
            return False

        # Start health monitoring
        asyncio.create_task(self._monitor_process_health())

        # Wait for full startup
        await asyncio.sleep(5)

        if self.process.poll() is not None:
            logger.error(
                f"Studio process exited during startup with return code: {self.process.returncode}"
            )
            return False

        logger.info("Roblox Studio started successfully")
        return True

    async def start_studio(self) -> bool:
        """Start Roblox Studio with the test place file"""
        # Verify Studio is installed
        if not self.studio_path.exists():
            logger.error(f"Roblox Studio not found at: {self.studio_path}")
            return False

        try:
            # Build place file
            if not self._build_placefile():
                logger.error("Failed to build place file")
                return False

            # Clean any stale lock files
            self._clean_lock_file()

            # Launch Studio
            if not await self._launch_studio_process():
                return False

            # Verify startup
            return await self._verify_studio_startup()

        except Exception as e:
            logger.error(f"Failed to start Studio: {e}")
            return False

    async def _terminate_studio_process(self) -> None:
        """Attempt graceful termination of Studio process"""
        if sys.platform == "win32":
            # Windows: Send WM_CLOSE
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid)],
                    check=False,
                    capture_output=True,
                )
                logger.debug("Sent graceful shutdown signal to Studio")
            except Exception as e:
                logger.warning(f"Could not send graceful shutdown: {e}")
        else:
            # Unix: Send SIGTERM
            self.process.terminate()
            logger.info("Sent SIGTERM to Studio process")

    async def _force_kill_studio_process(self) -> None:
        """Force kill Studio process"""
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                check=False,
                capture_output=True,
            )
        else:
            self.process.kill()

    async def stop_studio(self) -> bool:
        """Stop Roblox Studio gracefully"""
        if not self.process:
            logger.info("No Studio process to stop")
            return True

        try:
            logger.info("Stopping Roblox Studio...")

            # Attempt graceful termination
            await self._terminate_studio_process()

            # Wait for graceful shutdown
            try:
                await asyncio.wait_for(
                    self._wait_for_process(), timeout=app_config.shutdown_timeout
                )
                logger.info("Studio terminated gracefully")
            except TimeoutError:
                logger.warning("Graceful shutdown timed out, force killing...")

                # Force kill
                await self._force_kill_studio_process()

                # Wait for force kill
                try:
                    await asyncio.wait_for(self._wait_for_process(), timeout=5.0)
                    logger.info("Studio process force killed successfully")
                except TimeoutError:
                    logger.error("Failed to kill Studio process")

            # Cleanup
            self._clean_lock_file()
            self.process = None

            logger.info("Roblox Studio stopped")
            return True

        except Exception as e:
            logger.error(f"Failed to stop Studio: {e}")
            return False

    async def _wait_for_process(self) -> None:
        """Wait for process to terminate"""
        while self.process and self.process.poll() is None:
            await asyncio.sleep(0.5)

    async def _monitor_process_health(self) -> None:
        """Monitor the health of the Studio process"""
        try:
            check_count = 0
            while self.process:
                await asyncio.sleep(1)
                poll_result = self.process.poll()
                check_count += 1

                if poll_result is not None:
                    if poll_result == 0:
                        logger.info(f"Studio process exited normally after {check_count} seconds")
                    else:
                        logger.error(
                            f"Studio process exited with code {poll_result} after {check_count} seconds"
                        )
                    break
        except Exception as e:
            logger.error(f"Error monitoring Studio process health: {e}")

    def is_running(self) -> bool:
        """Check if Studio process is currently running"""
        return self.process is not None and self.process.poll() is None

    def is_healthy(self) -> dict:
        """Check health status of all components"""
        return {
            "studio_running": self.is_running(),
            "plugin_installed": self.plugin_manager.is_installed()
            if self.plugin_manager
            else False,
            "fflags_applied": self.fflag_manager._applied if self.fflag_manager else False,
            "placefile_built": self.built_unit_tests_placefile is not None
            and self.built_unit_tests_placefile.exists(),
        }


@asynccontextmanager
async def managed_studio():
    """Context manager that ensures Studio is properly started and stopped with FFlags and plugin"""
    studio_manager = StudioManager()

    # Stack context managers: FFlags -> Plugin -> Studio
    async with (
        managed_fflags(studio_manager.studio_dir) as fflag_manager,
        managed_plugin() as plugin_manager,
    ):
        # Store references to component managers
        studio_manager.fflag_manager = fflag_manager
        studio_manager.plugin_manager = plugin_manager

        try:
            success = await studio_manager.start_studio()
            if not success:
                raise RuntimeError("Failed to start Roblox Studio")

            yield studio_manager
        finally:
            await studio_manager.stop_studio()
