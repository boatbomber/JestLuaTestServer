import json
import logging
import shutil
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self):
        self.plugin_source = Path(__file__).parent.parent.parent.parent / "plugin"
        self.plugin_dest = (Path.home() / "AppData" / "Local" / "Roblox" / "Plugins" / "JestLuaTestServer.rbxm").resolve()
        self._installed = False
    
    async def install_plugin(self) -> bool:
        try:
            if not self.plugin_source.exists():
                logger.error(f"Plugin source directory not found: {self.plugin_source}")
                return False
            
            self.plugin_dest.parent.mkdir(parents=True, exist_ok=True)
            
            if self.plugin_dest.exists():
                logger.info(f"Removing existing plugin at {self.plugin_dest}")
                shutil.rmtree(self.plugin_dest)
                self._installed = False
            
            logger.info(f"Installing plugin from {self.plugin_source} to {self.plugin_dest}")


            if not (self.plugin_source / "DevPackages").exists():
                logger.info(f"DevPackages not found, installing...")
                try:
                    subprocess.check_output(["wally", "install"], stderr=subprocess.STDOUT, cwd=self.plugin_source)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Wally install failed: {e}")
                    return False
                
            (self.plugin_source / "src" / "server_info.json").write_text(
                json.dumps({
                    "host": settings.host,
                    "port": settings.port,
                }),
                encoding="utf-8",
                newline="\n",
            )

            try:
                subprocess.check_output(["rojo", "build", "-o", str(self.plugin_dest)], cwd=self.plugin_source)
            except subprocess.CalledProcessError as e:
                logger.error(f"Rojo build failed: {e}")
                return False

            self._installed = True
            logger.info("Plugin installed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to install plugin: {e}")
            return False
    
    async def uninstall_plugin(self) -> bool:
        try:
            if self.plugin_dest.exists():
                logger.info(f"Uninstalling plugin (file {self.plugin_dest})")
                self.plugin_dest.unlink()
                self._installed = False
                logger.info("Plugin uninstalled successfully")
                return True
            else:
                logger.info("Plugin not found, nothing to uninstall")
                return True
                
        except Exception as e:
            logger.error(f"Failed to uninstall plugin: {e}")
            return False
    
    def is_installed(self) -> bool:
        return self._installed and self.plugin_dest.exists()