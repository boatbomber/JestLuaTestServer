import json
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from app.config_manager import config as app_config

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self):
        self.plugin_source = Path(__file__).parent.parent.parent.parent / "plugin"
        self.plugin_install_dir = self._find_plugin_install_dir()
        self.plugin_dest = self.plugin_install_dir / "JestLuaTestServer.rbxm"
        self._installed = False

    def _find_plugin_install_dir_from_registry(self) -> Path | None:
        """Try to find plugin install dir from Windows registry"""
        if sys.platform != "win32":
            return None

        try:
            import winreg

            # Try current user registry first
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Roblox\RobloxStudio")
                plugin_install_dir, _ = winreg.QueryValueEx(key, "rbxm_local_plugin_last_directory")
                winreg.CloseKey(key)
                plugin_install_dir = Path(plugin_install_dir)
                if plugin_install_dir.exists():
                    logger.debug(
                        f"Found plugin install dir via registry (HKCU): {plugin_install_dir}"
                    )
                    return plugin_install_dir
            except (FileNotFoundError, OSError):
                pass

            # Try local machine registry
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Roblox\RobloxStudio")
                plugin_install_dir, _ = winreg.QueryValueEx(key, "rbxm_local_plugin_last_directory")
                winreg.CloseKey(key)
                plugin_install_dir = Path(plugin_install_dir)
                if plugin_install_dir.exists():
                    logger.debug(
                        f"Found plugin install dir via registry (HKLM): {plugin_install_dir}"
                    )
                    return plugin_install_dir
            except (FileNotFoundError, OSError):
                pass

        except ImportError:
            logger.debug("winreg module not available")
        except Exception as e:
            logger.debug(f"Registry lookup failed: {e}")

        return None

    def _find_plugin_install_dir(self) -> Path:
        """Get the plugin install directory, trying registry first"""
        dir_from_registry = self._find_plugin_install_dir_from_registry()
        if dir_from_registry:
            return dir_from_registry

        return (Path.home() / "AppData" / "Local" / "Roblox" / "Plugins").resolve()

    async def install_plugin(self) -> bool:
        try:
            if not self.plugin_source.exists():
                logger.error(f"Plugin source directory not found: {self.plugin_source}")
                return False

            self.plugin_dest.parent.mkdir(parents=True, exist_ok=True)

            if self.plugin_dest.exists():
                logger.debug(f"Removing existing plugin at {self.plugin_dest}")
                self.plugin_dest.unlink()
                self._installed = False

            logger.info(f"Installing plugin from {self.plugin_source} to {self.plugin_dest}")

            # Write temporary config file
            config_file = self.plugin_source / "src" / "serverConfig.json"
            config_file.write_text(
                json.dumps(app_config.model_dump()),
                encoding="utf-8",
                newline="\n",
            )

            try:
                subprocess.check_output(
                    ["rojo", "build", "-o", str(self.plugin_dest)], cwd=self.plugin_source
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Rojo build failed: {e}")
                return False
            finally:
                # Clean up temporary config file
                if config_file.exists():
                    config_file.unlink()
                    logger.debug("Cleaned up temporary serverConfig.json file")

            # Verify build output
            if not self.plugin_dest.exists():
                logger.error(f"Plugin build succeeded but output not found at {self.plugin_dest}")
                return False

            # Verify file size is reasonable (at least 1KB)
            if self.plugin_dest.stat().st_size < 1024:
                logger.error(
                    f"Plugin file seems too small: {self.plugin_dest.stat().st_size} bytes"
                )
                return False

            self._installed = True
            logger.info(f"Plugin installed successfully ({self.plugin_dest.stat().st_size} bytes)")
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
                logger.debug("Plugin not found, nothing to uninstall")
                return True

        except Exception as e:
            logger.error(f"Failed to uninstall plugin: {e}")
            return False

    def is_installed(self) -> bool:
        return self._installed and self.plugin_dest.exists()


# Context manager for managed plugin lifecycle
@asynccontextmanager
async def managed_plugin():
    """Context manager that ensures plugin is properly installed and uninstalled"""
    plugin = PluginManager()
    try:
        success = await plugin.install_plugin()
        if not success:
            raise RuntimeError("Failed to install Roblox Studio plugin")
        yield plugin
    finally:
        await plugin.uninstall_plugin()
