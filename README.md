# JestLuaTestServer

Expose a /test endpoint to run Jest Lua tests quickly and easily


# How this works

We spin up a server with a POST `/test` endpoint that takes in an rbxm binary blob.

This server also has a couple internal endpoints, `/_events` and `/_results` that will be used below.

Upon spinning up the server, it installs a local plugin for Roblox Studio, sets relevant FFlags, and opens Roblox Studio to a Baseplate. (The plugin is uninstalled when the server is shutting down.)
When an rbxm comes in through `/test`, it gets chunked and sent to the Studio Plugin via SSE on the `/_events` endpoint. The plugin then uses SerializationService to load the rbxm, runs Jest on it, and then send the results back up via `/_results`. Those results are then sent as the response to the original `/test` request.
