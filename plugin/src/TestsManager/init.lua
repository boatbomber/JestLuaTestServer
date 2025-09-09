--!strict
local HttpService = game:GetService("HttpService")
local SerializationService = game:GetService("SerializationService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local DevPackages = ReplicatedStorage:WaitForChild("DevPackages")
local Jest = require(DevPackages:WaitForChild("Jest", math.huge))

local logger = require(script:FindFirstChild("Logger")).new()

local runCLIOptions = {
	verbose = false,
	ci = true,
	-- json=true,
	testTimeout = 10 * 1000,
}

type TestId = string
type Ok<T> = { success: true, results: T }
type Err<E> = { success: false, error: E }
type Outcome<T, E> = Ok<T> | Err<E>
type ServerConfig = {
	host: string,
	port: number,
	test_timeout: number,
	log_level: string,
	bearer_token: string?,
}

local TestsManager = {}
TestsManager.__index = TestsManager

type TestsManagerData = {
	serverConfig: ServerConfig,
	serverUrl: string,

	sseClient: WebStreamClient?,
	sseClientConnections: { [string]: RBXScriptConnection },
	active: boolean,
	reconnectAttempts: number,
	maxReconnectAttempts: number,
	maxReconnectDelay: number,

	heartbeatTask: thread?,

	testRbxmBuffers: { [TestId]: buffer },
	testRbxmBufferOffsets: { [TestId]: number },
}

export type TestsManager = typeof(setmetatable({} :: TestsManagerData, TestsManager))
-- or alternatively, in the new type solver...
-- export type TestsManager = setmetatable<TestsManagerData, typeof(TestsManager)>

function TestsManager.init(): TestsManager
	local serverConfigModule = (script.Parent :: Instance):FindFirstChild("serverConfig")
	if not serverConfigModule then
		logger:fatal(
			"serverConfig module not found. Please ensure it is present in the same directory as TestsManager."
		)
	end

	local serverConfig = require(serverConfigModule)
	logger:setLevel(serverConfig.log_level)
	-- Subtracting 1 second to account for overhead cost. The server total timeout is N,
	-- the plugin has to receive the test, deserialize it, run it, and report the results.
	-- We want Jest to timeout the test before the server does, so we subtract 1 second.
	-- We can adjust this later if needed.
	runCLIOptions.testTimeout = serverConfig.test_timeout * 1000 - 1000

	local self = setmetatable({
		serverConfig = serverConfig,
		serverUrl = `http://{serverConfig.host}:{serverConfig.port}`,

		active = false,
		reconnectAttempts = 0,
		maxReconnectAttempts = 10,
		maxReconnectDelay = 30,
		sseClientConnections = {},
		heartbeatTask = nil,
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
	test.Parent = workspace

	logger:info(`Sending {testId} to Jest for execution...`)
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

	logger:debug(`Deserialized test {testId}`, test)

	return test
end

function TestsManager.reportTestOutcome(self: TestsManager, testId: TestId, outcome: Outcome<any, string>): boolean
	if outcome.success then
		logger:info(`Test {testId} completed successfully:`, outcome.results)
	else
		logger:warn(`Test {testId} failed:`, outcome.error)
	end

	local success, response = pcall(HttpService.RequestAsync, HttpService, {
		Url = `{self.serverUrl}/_results`,
		Method = "POST" :: "POST",
		Headers = {
			["Content-Type"] = "application/json",
			["Authorization"] = `Bearer {self.serverConfig.bearer_token}`,
		},
		Body = HttpService:JSONEncode({
			test_id = testId,
			outcome = outcome,
		}),
		Compress = Enum.HttpCompression.None,
	})

	if not success then
		logger:warn("Failed to report test outcome:", response)
		return false
	end

	logger:info("Reported test outcome for", testId)
	return true
end

function TestsManager.sendHeartbeat(self: TestsManager): boolean
	local success, response = pcall(HttpService.RequestAsync, HttpService, {
		Url = `{self.serverUrl}/_heartbeat`,
		Method = "POST" :: "POST",
		Headers = {
			["Content-Type"] = "application/json",
			["Authorization"] = `Bearer {self.serverConfig.bearer_token}`,
		},
		Body = "{}",
		Compress = Enum.HttpCompression.None,
	})

	if not success then
		logger:debug("Failed to send heartbeat:", response)
		return false
	end

	logger:trace("Sent heartbeat to server")
	return true
end

function TestsManager.startHeartbeat(self: TestsManager)
	if self.heartbeatTask then
		return -- Already running
	end

	self.heartbeatTask = task.spawn(function()
		while self.active do
			self:sendHeartbeat()
			task.wait(1) -- Send heartbeat every second
		end
	end)
	logger:debug("Started heartbeat task")
end

function TestsManager.stopHeartbeat(self: TestsManager)
	if self.heartbeatTask then
		task.cancel(self.heartbeatTask)
		self.heartbeatTask = nil
		logger:debug("Stopped heartbeat task")
	end
end

function TestsManager.awaitHealthyServer(self: TestsManager)
	local maxDelay = 30
	local attempts = 0
	local baseDelay = 0.5

	while true do
		local healthSuccess, healthResponse = pcall(HttpService.RequestAsync, HttpService, {
			Url = `{self.serverUrl}/health`,
			Method = "GET" :: "GET",
			Compress = Enum.HttpCompression.None,
		})
		attempts = attempts + 1

		if healthSuccess and healthResponse.StatusCode == 200 then
			logger:info(`Found healthy server at {self.serverUrl} in {attempts} attempts`)
			break
		end

		local delay = math.min(baseDelay * (2 ^ (attempts - 1)), maxDelay)

		if attempts == 1 then
			logger:warning("Waiting for server to become healthy...")
		elseif attempts % 5 == 0 then
			logger:warning(`Still waiting for server (attempt {attempts}, next check in {delay} seconds)...`)
		end

		task.wait(delay)
	end
end

function TestsManager.reconnectWithBackoff(self: TestsManager)
	self.reconnectAttempts += 1

	if self.reconnectAttempts > self.maxReconnectAttempts then
		logger:error(`Maximum reconnection attempts ({self.maxReconnectAttempts}) reached. Stopping reconnection.`)
		self:stop()
		return
	end

	local reconnectDelay = if self.reconnectAttempts == 1
		then 0
		else math.min(2 ^ (self.reconnectAttempts - 1), self.maxReconnectDelay)

	if reconnectDelay > 0 then
		logger:warning(
			`Reconnecting SSE client in {reconnectDelay} seconds (attempt {self.reconnectAttempts}/{self.maxReconnectAttempts})...`
		)
		task.wait(reconnectDelay)
	else
		logger:warning(
			`Reconnecting SSE client immediately (attempt {self.reconnectAttempts}/{self.maxReconnectAttempts})...`
		)
	end

	if self.active then
		local sseClient = self:connectSSEClient()
		if sseClient then
			-- Reset reconnect attempts on successful connection
			logger:info("SSE connection restored after", self.reconnectAttempts, "attempts")
			self.reconnectAttempts = 0
		else
			-- Failed to connect, will retry
			self:reconnectWithBackoff()
		end
	else
		logger:warning("Cancelling scheduled reconnect since client is no longer active")
	end
end

function TestsManager.connectSSEClient(self: TestsManager): WebStreamClient?
	local success, sseClient = pcall(function()
		return HttpService:CreateWebStreamClient(Enum.WebStreamClientType.SSE, {
			Url = `{self.serverUrl}/_events`,
			Headers = {
				["Content-Type"] = "text/event-stream",
				["Authorization"] = `Bearer {self.serverConfig.bearer_token}`,
			},
			Method = "GET",
		})
	end)

	if not success then
		logger:error("Failed to create SSE client: " .. tostring(sseClient))
		return nil
	else
		logger:info("Connected SSE Client to server")
	end

	-- Cleanup old connections
	for _, connection in self.sseClientConnections do
		connection:Disconnect()
	end

	self.sseClientConnections.MessageReceived = sseClient.MessageReceived:Connect(function(message)
		self:handleSSEMessage(message)
	end)
	self.sseClientConnections.Error = sseClient.Error:Connect(function(code, message)
		logger:warning("SSE error", code, message)
	end)
	self.sseClientConnections.Closed = sseClient.Closed:Connect(function()
		if self.active then
			logger:warning("SSE connection closed unexpectedly")
			-- Attempt to reconnect with exponential backoff
			-- (WebStreamClient has a time restriction imposed by the engine, even with a keep-alive heartbeat)
			self:reconnectWithBackoff()
		else
			logger:info("SSE connection closed")
		end
	end)

	self.sseClient = sseClient

	return sseClient
end

function TestsManager.handleSSEMessage(self: TestsManager, message: string)
	logger:trace("Received SSE message:", message)

	local event = string.match(message, "event:%s*(.-)%s*\n")
	if event == "ping" or event == nil then
		logger:trace("Treating message as a keep-alive ping")
		return
	end

	local raw_data = string.match(message, "data:%s*(.-)%s*\n")
	local data = if raw_data then HttpService:JSONDecode(raw_data) else {}
	logger:trace(data)

	-- Buffer rbxm chunks until completion message, then deserialize and run
	if event == "test_start" then
		logger:debug(`Received test start for {data.test_id}`)
		self.testRbxmBuffers[data.test_id] = buffer.create(data.total_size)
		self.testRbxmBufferOffsets[data.test_id] = 0
	elseif event == "test_chunk" then
		logger:debug(`Received test chunk for {data.test_id}`)
		local rbxmBuffer = self.testRbxmBuffers[data.test_id]
		local offset = self.testRbxmBufferOffsets[data.test_id]
		buffer.copy(rbxmBuffer, offset, data.chunk_buffer)
		self.testRbxmBufferOffsets[data.test_id] += buffer.len(data.chunk_buffer)
	elseif event == "test_end" then
		logger:debug(`Received test end for {data.test_id}`)
		task.spawn(function()
			local outcome = self:runTest(data.test_id)
			self:reportTestOutcome(data.test_id, outcome)

			self.testRbxmBuffers[data.test_id] = nil
			self.testRbxmBufferOffsets[data.test_id] = nil
		end)
	elseif event == "shutdown" then
		logger:info("Server is shutting down")
		self:stop()
	else
		logger:warning("unhandled event type:", event)
	end
end

function TestsManager.start(self: TestsManager)
	self.active = true
	self:awaitHealthyServer()
	self:connectSSEClient()
	self:startHeartbeat()
end

function TestsManager.stop(self: TestsManager)
	self.active = false
	self:stopHeartbeat()
	if self.sseClient then
		self.sseClient:Close()
	end
	for _, connection in self.sseClientConnections do
		connection:Disconnect()
	end
	logger:info("TestsManager stopped")
end

return TestsManager
