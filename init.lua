--- === SnippetsLabAutoTitle ===
---
--- Give untitled SnippetsLab snippets a title from a local LLM (LM Studio).
---
--- SnippetsLab loads its library into memory at launch and never re-reads
--- local file changes, so the title is written straight into the snippet file
--- and the app is relaunched in the background once it is hidden and idle.
--- The app never becomes frontmost (its quick window is a non-activating
--- panel), so "leaving the app" is not an event. The app saving the snippet
--- file is the only reliable signal, and that is what this Spoon watches.
---
--- Titles this Spoon wrote are regenerated when the body changes. A title the
--- person typed is never touched. That bookkeeping lives in the Python side
--- (bin/snippetslab-autotitle); this file only watches, debounces, and relaunches.
---
--- Download: https://github.com/insoul/SnippetsLabAutoTitle.spoon

local obj = {}
obj.__index = obj

obj.name = "SnippetsLabAutoTitle"
obj.version = "0.1"
obj.author = "insoul <insoo.jung+github@gmail.com>"
obj.homepage = "https://github.com/insoul/SnippetsLabAutoTitle.spoon"
obj.license = "MIT - https://opensource.org/licenses/MIT"

local function scriptPath()
    return debug.getinfo(2, "S").source:sub(2):match("(.*/)")
end
obj.spoonPath = scriptPath()

--- SnippetsLabAutoTitle.library
--- Variable
--- Directory that holds one .data file per snippet.
obj.library = os.getenv("HOME")
    .. "/Library/Mobile Documents/iCloud~com~renfei~SnippetsLab/main.snippetslablibrary/Database/Snippets"

obj.bundleID = "com.renfei.SnippetsLab"
obj.quietSeconds = 30          -- run the tool after this much silence
obj.relaunchIdleSeconds = 300  -- relaunch only after this much silence
obj.relaunchCheckSeconds = 60
obj.logger = hs.logger.new("SLAutoTitle", "info")

local task, rerun, quietTimer, relaunchTimer
local lastEvent = 0
local relaunchPending = false

local function lastLine(s)
    local last
    for line in (s or ""):gmatch("[^\n]+") do last = line end
    return last
end

local safeRun
local function runTool(self)
    if task then rerun = true; return end
    task = hs.task.new(self.tool, function(code, out, err)
        task = nil
        local ok, e = pcall(function()
            if code ~= 0 then
                self.logger.e("tool exit " .. tostring(code) .. ": " .. (err or ""))
                return
            end
            local summary = hs.json.decode(lastLine(out) or "") or {}
            self.logger.i(lastLine(out) or "no summary")
            if (summary.written or 0) > 0 then
                relaunchPending = true
                self:_armRelaunch()
            end
        end)
        if not ok then self.logger.e(tostring(e)) end
        if rerun then rerun = false; safeRun(self) end
    end, { "--library", self.library })
    if task then task:start() end
end

safeRun = function(self) local ok, e = pcall(runTool, self); if not ok then self.logger.e(tostring(e)) end end

function obj:_onEvent()
    lastEvent = os.time()
    if quietTimer then quietTimer:stop() end
    quietTimer = hs.timer.doAfter(self.quietSeconds, function()
        quietTimer = nil
        safeRun(self)
    end)
end

function obj:_armRelaunch()
    if relaunchTimer then return end
    relaunchTimer = hs.timer.doEvery(self.relaunchCheckSeconds, function()
        local ok, e = pcall(function() self:_tryRelaunch() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
end

local function disarm()
    if relaunchTimer then relaunchTimer:stop(); relaunchTimer = nil end
end

function obj:_tryRelaunch()
    if not relaunchPending then disarm(); return end
    local app = hs.application.get(self.bundleID)
    if not app then
        -- Not running: the next launch reads the new titles on its own.
        relaunchPending = false; disarm(); return
    end
    if os.time() - lastEvent < self.relaunchIdleSeconds then return end
    if not app:isHidden() and #app:visibleWindows() > 0 then return end

    relaunchPending = false
    disarm()
    local pid = app:pid()
    self.logger.i("relaunching SnippetsLab")
    app:kill()
    local tries = 0
    hs.timer.waitUntil(function()
        local ok, e = pcall(function()
            tries = tries + 1
            return hs.application.applicationForPID(pid) == nil or tries > 20
        end)
        if not ok then self.logger.e(tostring(e)); return true end
        return e
    end, function()
        local ok, e = pcall(function()
            if hs.application.applicationForPID(pid) then
                self.logger.w("SnippetsLab did not quit within 10s; not relaunching")
                relaunchPending = true
                self:_armRelaunch()
                return
            end
            -- `open -g` keeps focus where it is. hs.application.launchOrFocus would steal it.
            local t = hs.task.new("/usr/bin/open", nil, { "-g", "-b", self.bundleID })
            if t then t:start() end
            self.logger.i("relaunched")
        end)
        if not ok then self.logger.e(tostring(e)) end
    end, 0.5)
end

--- SnippetsLabAutoTitle:init()
--- Method
--- Resolves the bundled tool path. Called for you when the Spoon is loaded.
function obj:init()
    if not self.tool then
        self.tool = self.spoonPath .. "bin/snippetslab-autotitle"
    end
    return self
end

--- SnippetsLabAutoTitle:start()
--- Method
--- Start watching the library. Returns the Spoon object.
function obj:start()
    self:stop()
    self.watcher = hs.pathwatcher.new(self.library, function()
        local ok, e = pcall(function() self:_onEvent() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
    self.watcher:start()
    self.logger.i("watching " .. self.library)
    return self
end

--- SnippetsLabAutoTitle:stop()
--- Method
--- Stop watching and cancel pending timers.
function obj:stop()
    if self.watcher then self.watcher:stop(); self.watcher = nil end
    if quietTimer then quietTimer:stop(); quietTimer = nil end
    disarm()
    if task then task:terminate(); task = nil end
    rerun = false
    relaunchPending = false
    return self
end

--- SnippetsLabAutoTitle:runNow()
--- Method
--- Run the tool immediately, without waiting for the quiet period.
function obj:runNow()
    safeRun(self)
    return self
end

return obj
