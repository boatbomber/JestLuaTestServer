import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class StudioManager:
    def __init__(self):
        self.process = None
        self.empty_place_path = (Path(__file__).parent / "empty_place.rbxl").resolve()
        self.studio_dir = Path.home() / "AppData" / "Local" / "Roblox Studio"
        self.studio_path = self.studio_dir / "RobloxStudioBeta.exe"
        self.client_settings_path = self.studio_dir / "ClientSettings" / "ClientAppSettings.json"
        self.original_settings = None
        
    def _setup_fflags(self) -> bool:
        try:
            self.client_settings_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Backup original settings if they exist
            if self.client_settings_path.exists():
                with open(self.client_settings_path, 'r') as f:
                    self.original_settings = json.load(f)
                logger.info(f"Backed up original FFlags: {self.original_settings}")
            
            # Set required FFlags
            fflags = {
                "DFFlagEnableWebStreamClientInStudio": True,
                "DFFlagDisableWebStreamClientInStudioScripts": False,
                "DFIntWebStreamClientRequestTimeoutMs": 5000,
                "FFlagEnableLoadModule": True,
            }
            
            # Merge with existing settings if any
            if self.original_settings:
                merged_settings = {**self.original_settings, **fflags}
            else:
                merged_settings = fflags
            
            with open(self.client_settings_path, 'w') as f:
                json.dump(merged_settings, f, indent=2)
            
            logger.info(f"Set FFlags in {self.client_settings_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set FFlags: {e}")
            return False
    
    def _restore_fflags(self) -> bool:
        try:
            if self.original_settings is not None:
                with open(self.client_settings_path, 'w') as f:
                    json.dump(self.original_settings, f, indent=2)
                logger.info("Restored original FFlags")
            elif self.client_settings_path.exists():
                self.client_settings_path.unlink()
                logger.info("Removed FFlags file")
            return True
        except Exception as e:
            logger.error(f"Failed to restore FFlags: {e}")
            return False
    
    async def start_studio(self) -> bool:
        logger.info(f"Checking for Roblox Studio at: {self.studio_path}")
        if not self.studio_path.exists():
            logger.error(f"Roblox Studio not found at: {self.studio_path}")
            # Try to find Studio in alternative locations
            alt_paths = [
                Path.home() / "AppData" / "Local" / "Roblox" / "Versions" / "RobloxStudioBeta.exe",
                Path("C:/Program Files/Roblox/RobloxStudioBeta.exe"),
                Path("C:/Program Files (x86)/Roblox/RobloxStudioBeta.exe"),
            ]
            for alt_path in alt_paths:
                logger.info(f"Checking alternative path: {alt_path}")
                if alt_path.exists():
                    logger.info(f"Found Studio at alternative location: {alt_path}")
                    self.studio_path = alt_path
                    break
            else:
                logger.error("Could not find Roblox Studio in any known location")
                return False
        
        try:
            # Setup FFlags before starting Studio
            if not self._setup_fflags():
                logger.warning("Failed to setup FFlags, continuing anyway...")
            
            cmd = [
                str(self.studio_path),
                "-localPlaceFile", str(self.empty_place_path),
            ]
            
            logger.info(f"Starting Roblox Studio with command: {' '.join(cmd)}")
            
            if sys.platform == "win32":
                # On Windows, we need to ensure proper encoding and error handling
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
            
            logger.info(f"Studio process created with PID: {self.process.pid}")
            
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
            health_task = asyncio.create_task(self._monitor_process_health())

            await asyncio.sleep(5)
            
            if self.process.poll() is not None:
                logger.error(f"Studio process exited after startup with return code: {self.process.returncode}")
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
            
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], check=False)
            else:
                self.process.terminate()
            
            try:
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process()), 
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("Studio did not terminate gracefully, killing...")
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], check=False)
                else:
                    self.process.kill()

            # Clean up any existing lock file
            lock_file_path = Path(str(self.empty_place_path) + ".lock")
            if lock_file_path.exists():
                logger.info(f"Removing existing lock file: {lock_file_path}")
                try:
                    lock_file_path.unlink()
                    logger.info("Lock file removed successfully")
                except Exception as e:
                    logger.warning(f"Failed to remove lock file: {e}")
            
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
                    logger.error(f"Studio process exited with code {poll_result} after {check_count} seconds")
                    break
        except Exception as e:
            logger.error(f"Error monitoring Studio process health: {e}")
    
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None