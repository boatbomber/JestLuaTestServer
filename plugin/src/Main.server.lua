local HttpService = game:GetService("HttpService")
local SerializationService = game:GetService("SerializationService")

local server_info = require(script.Parent:WaitForChild("server_info"))
local server_url = `http://{server_info.host}:{server_info.port}`

local DevPackages = script.Parent:WaitForChild("DevPackages")

local Jest = require(DevPackages:WaitForChild("Jest"))

local runCLIOptions = {
	verbose = false,
	ci = true,
    -- json=true,
	testTimeout = 15000,
    testMatch = {
		"**/*.(spec|test)",
	},
	testPathIgnorePatterns = {
		"Packages",
		"DevPackages",
	},
}

local function deserializeRbxm(buf: buffer): any
    local instances =  SerializationService:DeserializeInstancesAsync(buf)
    assert(#instances == 1, "Expected exactly one root instance in the rbxm")
    return instances[1]
end

local function runTests(tests: Instance)
    local status, result = Jest.runCLI(script, runCLIOptions, { tests }):awaitStatus()

    if status == "Rejected" then
        error("Failed to run tests: ", result)
    elseif status == "Resolved" then
        print("Tests completed successfully", result)
    end

    -- TODO: Post result.results up to `{server_url}/_results`
end

local success, sse_client = pcall(function()
    return HttpService:CreateWebStreamClient(Enum.WebStreamClientType.SSE, {
        Url = `{server_url}/_events`,
        Method = "GET",
    })
end)

if not success then
    error("Failed to create SSE client: " .. tostring(sse_client))
else
    print("Loaded SSE Client")
end

--[[
sse_client.MessageReceived:Connect(function(message)
    print("Message received", message)
    -- local data = HttpService:JSONDecode(message)
    -- print(data)

    -- TODO: Buffer rbxm chunks until completion message, then deserialize and run
end)

sse_client.Error:Connect(function(code, message)
    print("SSE error", code, message)
end)

sse_client.Closed:Connect(function()
    print("SSE connection closed")
end)
--]]