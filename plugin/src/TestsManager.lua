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
type SuccessfulTestResult = {
	success: true,
	results: any,
}
type ErrorResult = {
	success: false,
	error: string,
}

local TestsManager = {}
TestsManager.testRbxmBuffers = {} :: { [TestId]: buffer }
TestsManager.testRbxmBufferOffsets = {} :: { [TestId]: number }

function TestsManager:runTest(testId: TestId): SuccessfulTestResult | ErrorResult
	local runSuccess, runResult = pcall(function()
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
	end)

	if not runSuccess then
		return {
			success = false,
			error = "Failed to run test: " .. tostring(runResult),
		}
	end

	return runResult
end

function TestsManager:deserializeTest(testId: string): any
	local buf = TestsManager.testRbxmBuffers[testId]
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

function TestsManager:reportTestOutcome(testId: TestId, outcome: SuccessfulTestResult | ErrorResult)
	if outcome.success then
		print("Test completed successfully:", outcome.results)
	else
		warn("Test failed:", outcome.error)
	end

	local success, response = pcall(HttpService.RequestAsync, HttpService, {
		Url = `{server_url}/_results`,
		Method = "POST",
		Headers = {
			["Content-Type"] = "application/json",
		},
		Body = HttpService:JSONEncode({
			test_id = testId,
			outcome = outcome,
		}),
	})

	if not success then
		warn("Failed to report test outcome:", response)
	else
		print("Reported test outcome for", testId)
	end
end

function TestsManager:awaitHealthyServer()
	local healthSuccess, healthResponse = pcall(HttpService.RequestAsync, HttpService, {
		Url = `{server_url}/health`,
		Method = "GET",
	})
	while not healthSuccess or healthResponse.StatusCode ~= 200 do
		wait(1)
		healthSuccess, healthResponse = pcall(HttpService.RequestAsync, HttpService, {
			Url = `{server_url}/health`,
			Method = "GET",
		})
	end
end

function TestsManager:connectSSEClient()
	local success, sse_client = pcall(function()
		return HttpService:CreateWebStreamClient(Enum.WebStreamClientType.SSE, {
			Url = `{server_url}/_events`,
			Headers = {
				["content-type"] = "application/json",
			},
			Method = "GET",
		})
	end)

	if not success then
		error("Failed to create SSE client: " .. tostring(sse_client))
	else
		print("Loaded SSE Client")
	end

	sse_client.MessageReceived:Connect(function(message)
		self:handleSSEMessage(message)
	end)
	sse_client.Error:Connect(function(code, message)
		print("SSE error", code, message)
	end)
	sse_client.Closed:Connect(function()
		print("SSE connection closed")
	end)

	workspace.KillSwitch.Changed:Connect(function()
		sse_client:Close()
	end)

	return sse_client
end

function TestsManager:handleSSEMessage(message: string)
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
		self:reportTestOutcome(data.test_id, outcome)

		self.testRbxmBuffers[data.test_id] = nil
		self.testRbxmBufferOffsets[data.test_id] = nil
	else
		print("unhandled event type:", event)
	end
end

function TestsManager:start()
	self:awaitHealthyServer()
	self:connectSSEClient()
end

return TestsManager
