import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class FFlagManager:
    """Manages Roblox Studio FFlags configuration"""

    REQUIRED_FFLAGS = {
        # For Jest
        "FFlagEnableLoadModule": "true",
    }

    def __init__(self, studio_dir: Path | None = None):
        self.studio_dir = studio_dir or (Path.home() / "AppData" / "Local" / "Roblox Studio")
        self.client_settings_path = self.studio_dir / "ClientSettings" / "ClientAppSettings.json"
        self.original_settings: dict | None = None
        self._applied = False

    def apply(self) -> bool:
        """Apply required FFlags to Studio configuration"""
        try:
            # Create directory if it doesn't exist
            self.client_settings_path.parent.mkdir(parents=True, exist_ok=True)

            # Backup original settings if they exist
            if self.client_settings_path.exists():
                with open(self.client_settings_path) as f:
                    self.original_settings = json.load(f)
                logger.debug(f"Backed up {len(self.original_settings)} existing FFlags")

            # Merge with existing settings
            merged_settings = {**(self.original_settings or {}), **self.REQUIRED_FFLAGS}

            # Write merged settings
            with open(self.client_settings_path, "w") as f:
                json.dump(merged_settings, f, indent=2)

            self._applied = True
            logger.info(
                f"Applied {len(self.REQUIRED_FFLAGS)} FFlags to {self.client_settings_path}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to apply FFlags: {e}")
            return False

    def restore(self) -> bool:
        """Restore original FFlags configuration"""
        if not self._applied:
            logger.debug("FFlags were not applied, nothing to restore")
            return True

        try:
            if self.original_settings is not None:
                # Restore original settings
                with open(self.client_settings_path, "w") as f:
                    json.dump(self.original_settings, f, indent=2)
                logger.info("Restored original FFlags")
            elif self.client_settings_path.exists():
                # No original settings, remove the file
                self.client_settings_path.unlink()
                logger.info("Removed FFlags file (no original settings)")

            self._applied = False
            return True

        except Exception as e:
            logger.error(f"Failed to restore FFlags: {e}")
            return False


@asynccontextmanager
async def managed_fflags(studio_dir: Path | None = None):
    """Context manager for managed FFlags lifecycle"""
    manager = FFlagManager(studio_dir)
    try:
        if not manager.apply():
            logger.warning("Failed to apply FFlags, continuing anyway...")
        yield manager
    finally:
        manager.restore()
