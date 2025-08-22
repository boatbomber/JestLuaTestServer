"""API key management for remote worker authentication"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class APIKeyManager:
    """Manages API keys for remote worker authentication"""

    def __init__(self, keys_file: Path | str = "api_keys.txt"):
        self.keys_file = Path(keys_file)
        self._keys: set[str] = set()

    def load(self) -> None:
        """Load API keys from file"""
        if not self.keys_file.exists():
            logger.warning(
                f"API keys file not found: {self.keys_file}"
                "\nRemote workers won't be able to access /test endpoint"
                "\nPlease add API keys to api_keys.txt file (one per line)"
            )
            self.keys_file.touch()
            return

        try:
            with open(self.keys_file) as f:
                # Read keys, strip whitespace, ignore empty lines and comments
                self._keys = {
                    line.strip() for line in f if line.strip() and not line.strip().startswith("#")
                }

            if self._keys:
                logger.info(f"Loaded {len(self._keys)} API key(s) from {self.keys_file}")
            else:
                logger.warning(
                    f"No valid API keys found in {self.keys_file}"
                    "\nRemote workers won't be able to access /test endpoint"
                    "\nPlease add API keys to api_keys.txt file (one per line)"
                )
        except Exception as e:
            logger.error(f"Failed to load API keys: {e}")
            self._keys = set()

    def is_valid_key(self, api_key: str) -> bool:
        """Check if an API key is valid"""
        return api_key in self._keys

    def get_key_count(self) -> int:
        """Get the number of loaded API keys"""
        return len(self._keys)


# Global instance
api_key_manager = APIKeyManager()
