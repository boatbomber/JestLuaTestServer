local Logger = {}
Logger.__index = Logger

type LevelName = "notset" | "trace" | "debug" | "info" | "warn" | "warning" | "error" | "fatal" | "critical"
type LevelValue = number

type LoggerData = {
	source: string,
	name: LevelName,
	value: LevelValue,
}

export type Logger = typeof(setmetatable({} :: LoggerData, Logger))

local LEVEL_VALUES: { [LevelName]: LevelValue } = {
	critical = 50,
	fatal = 50,
	error = 40,
	warning = 30,
	warn = 30,
	info = 20,
	debug = 10,
	trace = 5,
	notset = 0,
}

local function getValueForLevelName(levelName: string): LevelValue
	return LEVEL_VALUES[string.lower(levelName) :: LevelName] or 0
end

function Logger.new(level: string?): Logger
	local levelName = string.lower(level or "info")

	local self = setmetatable({
		name = levelName,
		value = getValueForLevelName(levelName),
		source = debug.info(2, "sn"),
	}, Logger) :: Logger

	return self
end

function Logger.setLevel(self: Logger, level: string): ()
	self.value = getValueForLevelName(level)
end

function Logger.getLevel(self: Logger): LevelName
	return self.name
end

function Logger.isEnabledFor(self: Logger, level: string): boolean
	local levelValue = getValueForLevelName(level)
	return levelValue >= self.value
end

function Logger.log(self: Logger, level: string, ...: any)
	if self:isEnabledFor(level) then
		print(string.format("- %s - %s -", string.upper(level), self.source), ...)
	end
end

function Logger.trace(self: Logger, ...: any)
	self:log("trace", ...)
end

function Logger.debug(self: Logger, ...: any)
	self:log("debug", ...)
end

function Logger.info(self: Logger, ...: any)
	self:log("info", ...)
end

function Logger.warn(self: Logger, ...: any)
	self:log("warn", ...)
end

function Logger.warning(self: Logger, ...: any)
	self:log("warning", ...)
end

function Logger.error(self: Logger, ...: any)
	self:log("error", ...)
end

function Logger.fatal(self: Logger, ...: any)
	self:log("fatal", ...)
end

function Logger.critical(self: Logger, ...: any)
	self:log("critical", ...)
end

return Logger
