# Jest Lua Test Server

FastAPI-based server that manages Roblox Studio instances and coordinates Jest Lua test execution.

## Overview

The server component of JestLuaTestServer provides a REST API for submitting tests and manages the lifecycle of Roblox Studio instances. It handles plugin installation, Studio configuration, test distribution via Server-Sent Events (SSE), and result collection.

## Features

- **Automatic Studio Management**: Launches and manages Roblox Studio processes
- **Plugin Installation**: Automatically builds and installs the test runner plugin
- **FFlag Configuration**: Sets required Studio flags for SSE support
- **Test Queue Management**: Handles concurrent test requests with queuing
  - Honestly, I'm just not sure if Jest would mess up if we run multiple at a time so I'm not risking it
- **Real-time Communication**: SSE-based bidirectional communication with plugin
- **Error Recovery**: Graceful handling of Studio crashes and network failures
- **Health Monitoring**: Continuous monitoring of Studio process health
- **Configurable Timeouts**: Per-test and global timeout configuration
- **Authentication System**: Dual authentication with API keys for remote workers and session tokens for plugin

## Installation

### Prerequisites

- Python 3.11 or higher
- [UV](https://github.com/astral-sh/uv) package manager
- [Rojo](https://rojo.space/) for building Roblox files
- [Wally](https://wally.run/) for managing Roblox packages
- Windows OS (for Roblox Studio)

### Setup

1. **Install UV** (if not already installed):
   ```bash
   pip install uv
   ```

2. **Install dependencies**:
   ```bash
   cd server
   uv pip install -e .
   ```

3. **Install development dependencies** (optional):
   ```bash
   uv pip install -e ".[dev]"
   ```

## Usage

### Setting Up Authentication

1. **Create API keys file** (`server/api_keys.txt`):
   ```
   # Add one API key per line
   worker1_key_abc123xyz789
   worker2_key_def456uvw012
   ```

2. **Generate secure API keys**:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

### Starting the Server

**Using the run script** (recommended):
```bash
cd server
uv run python run.py
```

**With custom configuration**:
```bash
JEST_TEST_SERVER_PORT=8080 JEST_TEST_SERVER_LOG_LEVEL=DEBUG uv run python run.py
```

**Disable authentication** (for local development only):
```bash
JEST_TEST_SERVER_ENABLE_AUTH=false uv run python run.py
```

### Server Startup Process

When the server starts, it:

1. **Loads API Keys**: Reads API keys from `api_keys.txt` for remote worker authentication
2. **Generates Session Token**: Creates a unique token for plugin internal endpoints
3. **Configures Studio**: Sets required FFlags in Studio's ClientSettings via FFlagManager
4. **Installs the Plugin**: Builds and installs the Roblox Studio plugin with embedded session token
5. **Builds Test Place**: Creates a Roblox place file with Jest dependencies
6. **Launches Studio**: Starts Roblox Studio with the test place via StudioManager
7. **Establishes Connection**: Waits for the plugin to connect via SSE
8. **Ready for Tests**: Begins accepting test submissions

### Submitting Tests

Submit test rbxm data to the `/test` endpoint with API key authentication:
```python
import requests

with open("tests.rbxm", "rb") as f:
    response = requests.post(
        "http://localhost:8325/test",
        data=f.read(),
        headers={
            "Content-Type": "application/octet-stream",
            "X-API-Key": "your-api-key-here"  # Required for authentication
        }
    )
    
result = response.json()
print(f"Test ID: {result['test_id']}")
print(f"Status: {result['status']}")
if result['status'] == 'completed':
    print(f"Results: {result['results']}")
else:
    print(f"Error: {result['error']}")
```

## API Reference

### Endpoints

#### `POST /test`
Submit a test for execution. Requires API key authentication.

**Request:**
- Method: `POST`
- Headers:
  - `Content-Type: application/octet-stream`
  - `X-API-Key: your-api-key` (required)
- Body: Binary `.rbxm` file containing test modules

**Response (200 OK):**
```json
{
  "test_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "results": {
    "success": true,
    "testResults": [...],
    "numTotalTests": 5,
    "numPassedTests": 5,
    "numFailedTests": 0
  }
}
```

**Response (Timeout):**
```json
{
  "test_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "timeout",
  "error": "Test execution timed out after 30 seconds"
}
```

**Response (Error):**
```json
{
  "test_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "error",
  "error": "Failed to deserialize test file"
}
```

#### `GET /health`
Check server and Studio status.

**Response:**
```json
{
  "status": "healthy",
  "studio_running": true,
  "plugin_installed": true,
  "fflags_applied": true,
  "placefile_built": true
}
```

#### `GET /_events` (Internal)
Server-Sent Events stream for plugin communication. Protected by session token.

**Event Types:**
- `ping`: Keepalive message
- `test_start`: Begin test transmission
- `test_chunk`: Binary chunk of test data
- `test_end`: Complete test transmission

#### `POST /_results` (Internal)
Receive test results from plugin. Protected by session token.

**Request:**
```json
{
  "test_id": "550e8400-e29b-41d4-a716-446655440000",
  "outcome": {
    "success": true,
    "results": {...}
  }
}
```

## Configuration

### Environment Variables

All environment variables use the prefix `JEST_TEST_SERVER_`:

| Variable | Default | Description |
|----------|---------|-------------|
| `JEST_TEST_SERVER_HOST` | `127.0.0.1` | Server bind address |
| `JEST_TEST_SERVER_PORT` | `8325` | Server port |
| `JEST_TEST_SERVER_TEST_TIMEOUT` | `30` | Test execution timeout (seconds) |
| `JEST_TEST_SERVER_SHUTDOWN_TIMEOUT` | `10` | Graceful shutdown timeout (seconds) |
| `JEST_TEST_SERVER_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `JEST_TEST_SERVER_CHUNK_SIZE` | `8192` | SSE chunk size for rbxm transfer (bytes) |
| `JEST_TEST_SERVER_CORS_ORIGINS` | `["*"]` | Allowed CORS origins (JSON array) |
| `JEST_TEST_SERVER_ENABLE_AUTH` | `true` | Enable authentication system |

### Configuration File

Create a `.env` file in the server directory:
```env
JEST_TEST_SERVER_HOST=0.0.0.0
JEST_TEST_SERVER_PORT=8080
JEST_TEST_SERVER_TEST_TIMEOUT=60
JEST_TEST_SERVER_LOG_LEVEL=DEBUG
```

### Studio FFlags

The server automatically configures these FFlags in `ClientSettings/ClientAppSettings.json`:

```json
{
  "FFlagEnableLoadModule": "true"
}
```

## Components

### FFlagManager

Manages Roblox Studio FFlag configuration:
- Applies required FFlags for Jest and SSE streaming
- Backs up existing FFlag configuration
- Restores original flags on shutdown
- Provides context manager for automatic cleanup

### PluginManager

Handles plugin lifecycle:
- Builds plugin from source using Rojo
- Injects server configuration
- Installs to Studio plugins directory
- Manages plugin updates and removal
- Provides context manager for automatic cleanup

### StudioManager

Manages Roblox Studio process:
- Locates Studio installation via registry and filesystem
- Coordinates FFlagManager and PluginManager
- Builds test place with dependencies
- Launches and monitors Studio process
- Handles graceful shutdown
- Provides unified health checking across all components

### Test Queue System

Manages test execution flow:
- Queues incoming test requests
- Distributes tests to plugin via SSE
- Tracks active tests with futures
- Enforces timeouts
- Collects and returns results

## Development

### Project Structure

```
server/
├── app/                        # Application code
│   ├── __init__.py
│   ├── main.py                 # FastAPI app and lifecycle
│   ├── config_manager.py       # Settings management
│   ├── dependencies.py         # Dependency injection
│   ├── auth.py                 # Authentication middleware
│   ├── api_keys.py             # API key management
│   ├── endpoints/              # API endpoints
│   │   ├── __init__.py
│   │   ├── events.py           # SSE endpoint (session token)
│   │   ├── results.py          # Results collection (session token)
│   │   └── test.py             # Test submission (API key)
│   └── utils/                  # Utilities
│       ├── __init__.py
│       ├── fflag_manager.py    # FFlag management
│       ├── plugin_manager.py   # Plugin management
│       └── studio_manager.py   # Studio management
├── api_keys.txt                # API keys (gitignored)
├── api_keys.txt.example        # Example API keys
├── pyproject.toml              # Project config
├── uv.lock                     # Locked deps
└── run.py                      # Entry point
```

### Debugging

Enable debug logging:
```bash
JEST_TEST_SERVER_LOG_LEVEL=DEBUG uv run python run.py
```

Monitor Studio output:
- Check Studio's output window for plugin logs
- Review server logs for communication issues
- Use the test client to send sample tests

Common issues:
- **Studio not found**: Check installation path in `studio_manager.py`
- **Plugin not loading**: Verify Rojo is installed and in PATH
- **SSE connection failed**: Check FFlags are properly set
- **Tests timing out**: Increase `TEST_TIMEOUT` configuration

## Error Handling

The server includes comprehensive error handling:

- **Studio Crashes**: Automatically detected and reported
- **Network Failures**: Graceful degradation with error messages
- **Test Timeouts**: Configurable timeouts with clear error responses
- **Plugin Errors**: Captured and returned in test results
- **Shutdown**: Graceful cleanup of Studio and plugin

## Performance Considerations

- **Persistent Studio**: Eliminates startup overhead (~5-10 seconds per test)
- **Chunked Transfer**: Large test files transferred in configurable chunks
- **Async Processing**: Non-blocking test execution
- **Queue Management**: Handles concurrent requests efficiently
- **Resource Cleanup**: Proper cleanup prevents memory leaks

## Security Notes

- **Dual Authentication System**:
  - API keys protect the `/test` endpoint from unauthorized remote workers
  - Session tokens protect internal endpoints (`/_events`, `/_results`) from external access
- **API Keys Management**:
  - Store in `api_keys.txt` (gitignored)
  - One key per line, comments with `#` supported
  - Generate secure keys with `secrets.token_urlsafe(32)`
- **Session Tokens**:
  - Automatically generated on server startup
  - Injected into plugin configuration
  - Valid only for current server session
- Server binds to localhost by default
- Test files are not persisted to disk
- Studio runs with user privileges

## License

This server is part of the JestLuaTestServer project and is licensed under the Apache License 2.0.