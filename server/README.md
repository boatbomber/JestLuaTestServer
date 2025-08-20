# Jest Lua Test Server

Python server for running Jest Lua tests in Roblox Studio.

## Setup

1. Install UV (Python package manager):
```bash
pip install uv
```

2. Install dependencies:
```bash
cd server
uv pip install -e .
```

## Running the Server

```bash
uv run python run.py
```

Or with uvicorn directly:
```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## API Endpoints

### POST /test
Run a Jest test with an rbxm file.

Request:
- Body: Binary rbxm data
- Content-Type: application/octet-stream

Response:
```json
{
  "test_id": "uuid",
  "status": "completed|timeout|error",
  "results": {
    "success": true,
    "passed": 10,
    "failed": 0,
    "skipped": 0,
    "duration": 1.5,
    "details": {}
  },
  "error": "error message if failed"
}
```

### GET /_events
Server-Sent Events endpoint for plugin communication.

### POST /_results
Internal endpoint for plugin to submit test results.

### GET /health
Health check endpoint.

## Configuration

Environment variables (prefix with `JEST_TEST_SERVER_`):
- `HOST`: Server host (default: 127.0.0.1)
- `PORT`: Server port (default: 8000)
- `TEST_TIMEOUT`: Test timeout in seconds (default: 30)
- `LOG_LEVEL`: Logging level (default: INFO)

## Development

Run tests:
```bash
uv run pytest
```

Format code:
```bash
uv run ruff format .
```

Lint:
```bash
uv run ruff check .
```