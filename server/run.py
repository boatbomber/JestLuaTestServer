import logging
import sys

import uvicorn

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def main():
    try:
        config = uvicorn.Config(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            timeout_graceful_shutdown=5,
            reload=False,
            log_level=settings.log_level.lower(),
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
