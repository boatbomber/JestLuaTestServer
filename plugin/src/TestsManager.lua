--!strict
local HttpService = game:GetService("HttpService")
local SerializationService = game:GetService("SerializationService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local DevPackages = ReplicatedStorage:WaitForChild("DevPackages")
local Jest = require(DevPackages:WaitForChild("Jest", math.huge))

local serverSettings = require(script.Parent:FindFirstChild("serverSettings"))
local server_url = `http://{serverSettings.host}:{serverSettings.port}`

_G.NOCOLOR = 1
local runCLIOptions = {
	verbose = false,
	ci = true,
	-- json=true,
	testTimeout = serverSettings.test_timeout,
	testMatch = {
		"**/*.(spec|test)",
	},
	testPathIgnorePatterns = {
		"Packages",
		"DevPackages",
	},
}

type TestId = string
type Ok<T> = { success: true, results: T }
type Err<E> = { success: false, error: E }
type Outcome<T, E> = Ok<T> | Err<E>

local TestsManager = {}
TestsManager.__index = TestsManager

type TestsManagerData = {
	sseClient: WebStreamClient?,
	sseClientConnections: { [string]: RBXScriptConnection },
	active: boolean,

	testRbxmBuffers: { [TestId]: buffer },
	testRbxmBufferOffsets: { [TestId]: number },
}

export type TestsManager = typeof(setmetatable({} :: TestsManagerData, TestsManager))
-- or alternatively, in the new type solver...
-- export type TestsManager = setmetatable<TestsManagerData, typeof(TestsManager)>

function TestsManager.init(): TestsManager
	local self = setmetatable({
		active = false,
		sseClientConnections = {},
		testRbxmBuffers = {},
		testRbxmBufferOffsets = {},
	}, TestsManager) :: TestsManager

	self:start()

	-- We can toggle the boolean value to manually disconnect during development or debugging
	local KillSwitch = workspace:FindFirstChild("KillSwitch")
	if KillSwitch then
		KillSwitch.Changed:Connect(function()
			self:stop()
		end)
	end

	return self
end

function TestsManager._runTestUnsafe(self: TestsManager, testId: TestId): Outcome<any, string>
	local test = self:deserializeTest(testId)

	local status, jestResult = Jest.runCLI(script, runCLIOptions, { test }):awaitStatus()

	test:Destroy()

	if status == "Rejected" then
		return {
			success = false,
			error = tostring(jestResult),
		}
	end

	return {
		success = true,
		results = jestResult.results,
	}
end

function TestsManager.runTest(self: TestsManager, testId: TestId): Outcome<any, string>
	local runSuccess, runResult = pcall(function()
		return self:_runTestUnsafe(testId)
	end)

	if not runSuccess then
		return {
			success = false,
			error = "Failed to run test: " .. tostring(runResult),
		}
	end

	return runResult
end

function TestsManager.deserializeTest(self: TestsManager, testId: string): Instance
	local buf = self.testRbxmBuffers[testId]
	assert(buf, "No buffer found for testId: " .. testId)

	local instances = SerializationService:DeserializeInstancesAsync(buf)
	assert(#instances == 1, "Expected exactly one root instance in the rbxm")
	local test = instances[1]

	if not test:FindFirstChild("jest.config") then
		local config = Instance.new("ModuleScript")
		config.Name = "jest.config"
		config.Source = [[
		return {	
			testMatch = {
				"**/*.(spec|test)",
			},
			testPathIgnorePatterns = {
				"Packages",
				"DevPackages",
			}
		}
		]]
		config.Parent = test
	end

	return test
end

function TestsManager.reportTestOutcome(testId: TestId, outcome: Outcome<any, string>): boolean
	if outcome.success then
		print("Test completed successfully:", outcome.results)
	else
		warn("Test failed:", outcome.error)
	end

	local success, response = pcall(HttpService.RequestAsync, HttpService, {
		Url = `{server_url}/_results`,
		Method = "POST" :: "POST",
		Headers = {
			["Content-Type"] = "application/json",
		},
		Body = HttpService:JSONEncode({
			test_id = testId,
			outcome = outcome,
		}),
		Compress = Enum.HttpCompression.None,
	})

	if not success then
		warn("Failed to report test outcome:", response)
		return false
	end

	print("Reported test outcome for", testId)
	return true
end

function TestsManager.awaitHealthyServer()
	local healthSuccess, healthResponse = pcall(HttpService.RequestAsync, HttpService, {
		Url = `{server_url}/health`,
		Method = "GET" :: "GET",
		Compress = Enum.HttpCompression.None,
	})
	while not healthSuccess or healthResponse.StatusCode ~= 200 do
		wait(1)
		healthSuccess, healthResponse = pcall(HttpService.RequestAsync, HttpService, {
			Url = `{server_url}/health`,
			Method = "GET" :: "GET",
			Compress = Enum.HttpCompression.None,
		})
	end
end

function TestsManager.connectSSEClient(self: TestsManager): WebStreamClient
	local success, sseClient = pcall(function()
		return HttpService:CreateWebStreamClient(Enum.WebStreamClientType.SSE, {
			Url = `{server_url}/_events`,
			Headers = {
				["content-type"] = "application/json",
			},
			Method = "GET",
		})
	end)

	if not success then
		error("Failed to create SSE client: " .. tostring(sseClient))
	else
		print("Loaded SSE Client")
	end

	-- Cleanup old connections
	for _, connection in self.sseClientConnections do
		connection:Disconnect()
	end

	self.sseClientConnections.MessageReceived = sseClient.MessageReceived:Connect(function(message)
		self:handleSSEMessage(message)
	end)
	self.sseClientConnections.Error = sseClient.Error:Connect(function(code, message)
		print("SSE error", code, message)
	end)
	self.sseClientConnections.Closed = sseClient.Closed:Connect(function()
		print("SSE connection closed")
		if self.active then
			-- Attempt to reconnect if the manager is still active
			-- (WebStreamClient has a time restriction imposed by the engine, even with a keep-alive heartbeat)
			print("Reconnecting SSE client...")
			self:connectSSEClient()
		end
	end)

	self.sseClient = sseClient

	return sseClient
end

function TestsManager.handleSSEMessage(self: TestsManager, message: string)
	print("received", message)

	local event = string.match(message, "event:%s*(.-)%s*\n")
	if event == "ping" or event == nil then
		return
	end

	local raw_data = string.match(message, "data:%s*(.-)%s*\n")
	local data = if raw_data then HttpService:JSONDecode(raw_data) else {}
	-- print(data)

	-- Buffer rbxm chunks until completion message, then deserialize and run
	if event == "test_start" then
		self.testRbxmBuffers[data.test_id] = buffer.create(data.total_size)
		self.testRbxmBufferOffsets[data.test_id] = 0
	elseif event == "test_chunk" then
		local rbxmBuffer = self.testRbxmBuffers[data.test_id]
		local offset = self.testRbxmBufferOffsets[data.test_id]
		buffer.copy(rbxmBuffer, offset, data.chunk_buffer)
		self.testRbxmBufferOffsets[data.test_id] += buffer.len(data.chunk_buffer)
	elseif event == "test_end" then
		local outcome = self:runTest(data.test_id)
		self.reportTestOutcome(data.test_id, outcome)

		self.testRbxmBuffers[data.test_id] = nil
		self.testRbxmBufferOffsets[data.test_id] = nil
	elseif event == "shutdown" then
		print("Server is shutting down")
		self:stop()
	else
		print("unhandled event type:", event)
	end
end

function TestsManager.start(self: TestsManager)
	self.active = true
	self.awaitHealthyServer()
	self:connectSSEClient()
end

function TestsManager.stop(self: TestsManager)
	self.active = false
	if self.sseClient then
		self.sseClient:Close()
	end
	for _, connection in self.sseClientConnections do
		connection:Disconnect()
	end
	print("TestsManager stopped")
end

return TestsManager
