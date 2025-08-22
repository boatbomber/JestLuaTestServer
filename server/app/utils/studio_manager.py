import asyncio
import json
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from app.config_manager import config as app_config

logger = logging.getLogger(__name__)


class StudioManager:
    def __init__(self):
        self.process = None
        self.built_unit_tests_placefile: Path | None = None
        self.unit_tests_place_dir = (Path(__file__).parent / "unit_tests_place").resolve()
        self.studio_dir = Path.home() / "AppData" / "Local" / "Roblox Studio"
        self.studio_path = self.studio_dir / "RobloxStudioBeta.exe"
        self.client_settings_path = self.studio_dir / "ClientSettings" / "ClientAppSettings.json"
        self.original_settings = None

    def _setup_fflags(self) -> bool:
        try:
            self.client_settings_path.parent.mkdir(parents=True, exist_ok=True)

            # Backup original settings if they exist
            if self.client_settings_path.exists():
                with open(self.client_settings_path) as f:
                    self.original_settings = json.load(f)

            # Set required FFlags
            fflags = {
                "DFFlagEnableHttpStreaming": "true",
                "DFFlagDisableWebStreamClientInStudioScripts": "false",
                "DFFlagEnableWebStreamClientInStudio": "true",
                "DFFlagHttpServiceRequestTimeout": "true",
                "DFIntWebStreamClientRequestTimeoutMs": "100000",
                "FFlagEnableLoadModule": "true",
            }

            # Merge with existing settings if any
            if self.original_settings:
                merged_settings = {**self.original_settings, **fflags}
            else:
                merged_settings = fflags

            with open(self.client_settings_path, "w") as f:
                json.dump(merged_settings, f, indent=2)

            logger.info(f"Set FFlags in {self.client_settings_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to set FFlags: {e}")
            return False

    def _restore_fflags(self) -> bool:
        try:
            if self.original_settings is not None:
                with open(self.client_settings_path, "w") as f:
                    json.dump(self.original_settings, f, indent=2)
                logger.info("Restored original FFlags")
            return True
        except Exception as e:
            logger.error(f"Failed to restore FFlags: {e}")
            return False

    def build_placefile(self) -> bool:
        if not (self.unit_tests_place_dir / "DevPackages").exists():
            logger.info("DevPackages not found, installing...")
            try:
                subprocess.check_output(
                    ["wally", "install"], stderr=subprocess.STDOUT, cwd=self.unit_tests_place_dir
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Wally install failed: {e}")
                return False

        subprocess.check_output(
            ["rojo", "build", "-o", "build.rbxl"], cwd=self.unit_tests_place_dir
        )
        self.built_unit_tests_placefile = (self.unit_tests_place_dir / "build.rbxl").resolve()
        return True

    def _find_studio_from_registry(self) -> Path | None:
        """Try to find Studio path from Windows registry"""
        if sys.platform != "win32":
            return None

        try:
            import winreg

            # Try current user registry first
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

    async def start_studio(self) -> bool:
        logger.debug(f"Checking for Roblox Studio at: {self.studio_path}")
        if not self.studio_path.exists():
            logger.error(f"Roblox Studio not found at: {self.studio_path}")

            # Try registry lookup first (Windows only)
            registry_path = self._find_studio_from_registry()
            if registry_path:
                self.studio_path = registry_path
            else:
                # Try to find Studio in alternative locations
                alt_paths = [
                    Path.home()
                    / "AppData"
                    / "Local"
                    / "Roblox"
                    / "Versions"
                    / "RobloxStudioBeta.exe",
                    Path("C:/Program Files/Roblox/RobloxStudioBeta.exe"),
                    Path("C:/Program Files (x86)/Roblox/RobloxStudioBeta.exe"),
                ]
                for alt_path in alt_paths:
                    logger.debug(f"Checking alternative path: {alt_path}")
                    if alt_path.exists():
                        logger.debug(f"Found Studio at alternative location: {alt_path}")
                        self.studio_path = alt_path
                        break
                else:
                    logger.error("Could not find Roblox Studio in any known location")
                    return False

        try:
            # Setup FFlags before starting Studio
            if not self._setup_fflags():
                logger.warning("Failed to setup FFlags, continuing anyway...")

            if not self.build_placefile():
                logger.error("Failed to build placefile, cannot launch")
                return False

            cmd = [
                str(self.studio_path),
                "-localPlaceFile",
                str(self.built_unit_tests_placefile),
            ]

            logger.info(f"Starting Roblox Studio with command: {' '.join(cmd)}")

            if sys.platform == "win32":
                # On Windows, we need to ensure proper encoding and error handling
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

            # Check if process started successfully
            await asyncio.sleep(0.1)
            initial_poll = self.process.poll()
            if initial_poll is not None:
                logger.error(f"Studio process died immediately with return code: {initial_poll}")
                # Try to read any remaining output
                stdout, stderr = self.process.communicate()
                if stdout:
                    logger.error(f"Final STDOUT: {stdout}")
                if stderr:
                    logger.error(f"Final STDERR: {stderr}")
                return False

            # Also start a task to monitor process health
            asyncio.create_task(self._monitor_process_health())

            await asyncio.sleep(5)

            if self.process.poll() is not None:
                logger.error(
                    f"Studio process exited after startup with return code: {self.process.returncode}"
                )
                return False

            logger.info("Roblox Studio started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to start Studio: {e}")
            return False

    async def stop_studio(self) -> bool:
        if not self.process:
            logger.info("No Studio process to stop")
            return True

        try:
            logger.info("Stopping Roblox Studio...")

            # First try graceful shutdown (SIGTERM on Unix, WM_CLOSE on Windows)
            if sys.platform == "win32":
                # Try graceful close first
                try:
                    # Send WM_CLOSE to all windows of the process
                    subprocess.run(
                        ["taskkill", "/PID", str(self.process.pid)],
                        check=False,
                        capture_output=True,
                    )
                    logger.debug("Sent graceful shutdown signal to Studio")
                except Exception as e:
                    logger.warning(f"Could not send graceful shutdown: {e}")
            else:
                self.process.terminate()
                logger.info("Sent SIGTERM to Studio process")

            # Wait for graceful shutdown
            try:
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process()),
                    timeout=app_config.shutdown_timeout,
                )
                logger.info("Studio terminated gracefully")
            except TimeoutError:
                logger.warning("Studio did not terminate gracefully, escalating to force kill...")

                # Force kill if graceful shutdown failed
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        check=False,
                        capture_output=True,
                    )
                else:
                    self.process.kill()

                # Wait for force kill to complete
                try:
                    await asyncio.wait_for(
                        asyncio.create_task(self._wait_for_process()), timeout=5.0
                    )
                    logger.info("Studio process force killed successfully")
                except TimeoutError:
                    logger.error("Failed to kill Studio process even with force kill")

            # Clean up any existing lock file
            lock_file_path = Path(str(self.built_unit_tests_placefile) + ".lock")
            if lock_file_path.exists():
                logger.debug(f"Removing existing lock file: {lock_file_path}")
                try:
                    lock_file_path.unlink()
                    logger.debug("Lock file removed successfully")
                except Exception as e:
                    logger.warning(f"Failed to clean up stale lock file: {e}")

            self.process = None

            # Restore original FFlags after stopping Studio
            self._restore_fflags()

            logger.info("Roblox Studio stopped")
            return True

        except Exception as e:
            logger.error(f"Failed to stop Studio: {e}")
            return False

    async def _wait_for_process(self):
        while self.process and self.process.poll() is None:
            await asyncio.sleep(0.5)

    async def _monitor_process_health(self):
        """Monitor the health of the Studio process"""
        try:
            check_count = 0
            while self.process:
                await asyncio.sleep(1)
                poll_result = self.process.poll()
                check_count += 1

                if poll_result is not None:
                    logger.error(
                        f"Studio process exited with code {poll_result} after {check_count} seconds"
                    )
                    break
        except Exception as e:
            logger.error(f"Error monitoring Studio process health: {e}")

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


# Context manager for managed Studio lifecycle
@asynccontextmanager
async def managed_studio():
    """Context manager that ensures Studio is properly started and stopped"""
    studio = StudioManager()
    try:
        success = await studio.start_studio()
        if not success:
            raise RuntimeError("Failed to start Roblox Studio")
        yield studio
    finally:
        await studio.stop_studio()
