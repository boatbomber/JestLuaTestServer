import logging
import sys

import uvicorn

from app.config_manager import config as app_config

logging.basicConfig(
    level=getattr(logging, app_config.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def main():
    try:
        config = uvicorn.Config(
            "app.main:app",
            host=app_config.host,
            port=app_config.port,
            timeout_graceful_shutdown=app_config.shutdown_timeout,
            reload=False,
            log_level=app_config.log_level.lower(),
        )
        server = uvicorn.Server(config)
        server.run()
    except KeyboardInterrupt:
        logging.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
