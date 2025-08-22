import json
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from app.auth import internal_auth
from app.config_manager import config as app_config

logger = logging.getLogger(__name__)


class PluginManager:
    """Manages Roblox Studio plugin installation and lifecycle"""

    PLUGIN_NAME = "JestLuaTestServer.rbxm"
    CONFIG_FILE_NAME = "serverConfig.json"
    MIN_PLUGIN_SIZE = 1024  # Minimum expected plugin size in bytes

    def __init__(self):
        # Paths
        self.plugin_source = Path(__file__).parent.parent.parent.parent / "plugin"
        self.plugin_install_dir = self._find_plugins_directory()
        self.plugin_dest = self.plugin_install_dir / self.PLUGIN_NAME

        # State
        self._installed = False

    def _find_plugins_directory(self) -> Path:
        """Find Roblox Studio local plugins path"""
        default_path = Path.home() / "AppData" / "Local" / "Roblox" / "Plugins"

        # Check default location first
        if default_path.exists():
            return default_path

        # Try registry lookup (Windows only)
        registry_path = self._find_plugins_directory_from_registry()
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
                logger.debug(f"Found Studio plugins at alternative location: {path}")
                return path

        # Return default path even if not found (will error later with clear message)
        return default_path

    def _find_plugins_directory_from_registry(self) -> Path | None:
        """Try to find plugin install dir from Windows registry"""
        if sys.platform != "win32":
            return None

        try:
            import winreg

            registry_keys = [
                (winreg.HKEY_CURRENT_USER, "HKCU"),
                (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
            ]

            for root_key, key_name in registry_keys:
                try:
                    key = winreg.OpenKey(root_key, r"Software\Roblox\RobloxStudio")
                    plugin_dir, _ = winreg.QueryValueEx(key, "rbxm_local_plugin_last_directory")
                    winreg.CloseKey(key)

                    plugin_dir = Path(plugin_dir)
                    if plugin_dir.exists():
                        logger.debug(f"Found plugin dir via registry ({key_name}): {plugin_dir}")
                        return plugin_dir
                except (FileNotFoundError, OSError):
                    continue

        except ImportError:
            logger.debug("winreg module not available")
        except Exception as e:
            logger.debug(f"Registry lookup failed: {e}")

        return None

    def _write_config_file(self) -> Path:
        """Write temporary server configuration file for plugin"""
        config_file = self.plugin_source / "src" / self.CONFIG_FILE_NAME

        # Create config dict
        config_data = app_config.model_dump()

        # Add bearer token to config if authentication is enabled
        if app_config.enable_auth:
            config_data["bearer_token"] = internal_auth.get_session_token()
            logger.debug("Added bearer token to plugin config")

        config_file.write_text(
            json.dumps(config_data),
            encoding="utf-8",
            newline="\n",
        )
        logger.debug(f"Created temporary config file: {config_file}")
        return config_file

    def _remove_existing_plugin(self) -> None:
        """Remove existing plugin if present"""
        if self.plugin_dest.exists():
            logger.debug(f"Removing existing plugin at {self.plugin_dest}")
            self.plugin_dest.unlink()
            self._installed = False

    def _build_plugin(self) -> bool:
        """Build plugin using Rojo"""
        try:
            config_file = self._write_config_file()
            subprocess.check_output(
                ["rojo", "build", "-o", str(self.plugin_dest)],
                cwd=self.plugin_source,
                stderr=subprocess.STDOUT,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Rojo build failed: {e.output if hasattr(e, 'output') else e}")
            return False
        finally:
            # Always clean up config file
            if config_file.exists():
                config_file.unlink()
                logger.debug("Cleaned up temporary config file")

    def _verify_plugin_build(self) -> bool:
        """Verify the built plugin is valid"""
        if not self.plugin_dest.exists():
            logger.error(f"Plugin build succeeded but output not found at {self.plugin_dest}")
            return False

        file_size = self.plugin_dest.stat().st_size
        if file_size < self.MIN_PLUGIN_SIZE:
            logger.error(
                f"Plugin file too small: {file_size} bytes (minimum: {self.MIN_PLUGIN_SIZE})"
            )
            return False

        logger.info(f"Plugin built successfully ({file_size} bytes)")
        return True

    async def install_plugin(self) -> bool:
        """Install the plugin to Roblox Studio"""
        try:
            # Verify source exists
            if not self.plugin_source.exists():
                logger.error(f"Plugin source not found: {self.plugin_source}")
                return False

            # Ensure destination directory exists
            self.plugin_dest.parent.mkdir(parents=True, exist_ok=True)

            # Remove existing plugin
            self._remove_existing_plugin()

            logger.info(f"Installing plugin: {self.plugin_source} -> {self.plugin_dest}")

            # Build the plugin
            if not self._build_plugin():
                return False

            # Verify build
            if not self._verify_plugin_build():
                return False

            self._installed = True
            return True

        except Exception as e:
            logger.error(f"Failed to install plugin: {e}")
            return False

    async def uninstall_plugin(self) -> bool:
        """Uninstall the plugin from Roblox Studio"""
        try:
            if self.plugin_dest.exists():
                logger.info(f"Uninstalling plugin: {self.plugin_dest}")
                self.plugin_dest.unlink()
                self._installed = False
                logger.info("Plugin uninstalled successfully")
            else:
                logger.debug("Plugin not found, nothing to uninstall")

            return True

        except Exception as e:
            logger.error(f"Failed to uninstall plugin: {e}")
            return False

    def is_installed(self) -> bool:
        """Check if plugin is currently installed"""
        return self._installed and self.plugin_dest.exists()


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
