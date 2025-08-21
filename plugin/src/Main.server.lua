if true then
	warn(
		"CreateWebStreamClient is currently broken for Studio plugins."
			.. "\nUntil that's fixed, we include the relevant code as a ModuleScript for you to manually require in the command bar."
			.. "\nRun: `require(game.ServerStorage.TestsManager):start()`"
	)

	script.Parent.TestsManager:Clone().Parent = game.ServerStorage
	script.Parent.serverSettings:Clone().Parent = game.ServerStorage

	return nil
end

local TestsManager = require(script.Parent.TestsManager)
TestsManager:start()
