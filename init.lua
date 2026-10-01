--- === SnippetsLab ===
---
--- Hammerspoon helpers for SnippetsLab, one module per feature.
---
---   autotitle  give untitled snippets a title from a local LLM (LM Studio).
---              See autotitle.lua and docs/design.md.
---   capture    ⌥C saves the selected text or clipboard as a new snippet,
---              titled by the same LLM, through SnippetsLab 2.7's `lab create`.
---              See capture.lua.
---
--- Each feature is a plain Lua module next to this file, exposed as
--- `spoon.SnippetsLab.<feature>`. start()/stop() here fan out to every feature;
--- call a feature's own start()/stop() to run only that one.
---
--- Download: https://github.com/insoul/SnippetsLab.spoon

local obj = {}
obj.__index = obj

obj.name = "SnippetsLab"
obj.version = "0.2"
obj.author = "insoul <insoo.jung+github@gmail.com>"
obj.homepage = "https://github.com/insoul/SnippetsLab.spoon"
obj.license = "MIT - https://opensource.org/licenses/MIT"

local function scriptPath()
    return debug.getinfo(2, "S").source:sub(2):match("(.*/)")
end
obj.spoonPath = scriptPath()

obj.features = { "autotitle", "capture" }

--- SnippetsLab:init()
--- Method
--- Loads every feature module. Called for you when the Spoon is loaded.
function obj:init()
    for _, name in ipairs(self.features) do
        local feature = dofile(self.spoonPath .. name .. ".lua")
        if feature.init then feature:init() end
        self[name] = feature
    end
    return self
end

--- SnippetsLab:start()
--- Method
--- Starts every feature. Returns the Spoon object.
function obj:start()
    for _, name in ipairs(self.features) do
        local ok, e = pcall(function() self[name]:start() end)
        if not ok then hs.logger.new("SnippetsLab", "info").e(name .. ": " .. tostring(e)) end
    end
    return self
end

--- SnippetsLab:stop()
--- Method
--- Stops every feature. Returns the Spoon object.
function obj:stop()
    for _, name in ipairs(self.features) do
        local ok, e = pcall(function() self[name]:stop() end)
        if not ok then hs.logger.new("SnippetsLab", "info").e(name .. ": " .. tostring(e)) end
    end
    return self
end

return obj
