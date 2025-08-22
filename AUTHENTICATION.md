# Authentication System

The Jest Lua Test Server uses a dual authentication system to secure different endpoints:

## 1. API Key Authentication (Remote Workers)

The `/test` endpoint is protected by API keys to allow authorized remote workers to submit tests.

### Setup

1. Create an `api_keys.txt` file in the `server/` directory
2. Add one API key per line (empty lines and lines starting with `#` are ignored)
3. Generate secure API keys using:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

### Usage

Remote workers must include the API key in the `X-API-Key` header:

```bash
curl -X POST http://your-server:8325/test \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @test.rbxm
```

## 2. Session Token Authentication (Plugin)

Internal endpoints (`/_events` and `/_results`) are protected by a session-specific Bearer token that is automatically generated and injected into the plugin configuration.

### How it Works

1. When the server starts, it generates a unique session token
2. This token is automatically injected into the plugin's `serverConfig` when the plugin is built
3. The plugin uses this token to authenticate with internal endpoints
4. The token is valid only for the current server session

### Endpoints

- `/_events` - SSE endpoint for receiving test data (Bearer token required)
- `/_results` - Endpoint for submitting test results (Bearer token required)
- `/test` - Public endpoint for submitting tests (API key required)

## Configuration

Authentication can be configured via environment variables:

- `JEST_TEST_SERVER_ENABLE_AUTH` - Set to `false` to disable all authentication (default: `true`)
- `JEST_TEST_SERVER_ENV` - Set to `test` to disable authentication for testing

## Security Notes

1. **Never commit `api_keys.txt` to version control** - It's already in `.gitignore`
2. **Session tokens are ephemeral** - They're regenerated each time the server starts
3. **API keys should be kept secret** - Treat them like passwords
4. **Use HTTPS in production** - Authentication tokens are sent in headers