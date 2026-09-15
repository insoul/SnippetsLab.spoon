--- === SnippetsLabAutoTitle ===
---
--- Give untitled SnippetsLab snippets a title from a local LLM (LM Studio).
---
--- SnippetsLab keeps its library in memory and, on every save, rewrites the
--- whole package from that memory: a file changed behind its back is put back
--- to what the app last read. So titles are written only while the app is
--- closed. The work is split in two: after 30 s of silence the Python tool
--- *plans* titles (LLM calls, no file writes); after 5 min of silence with the
--- app hidden, this Spoon quits the app, runs the tool with --apply (writes
--- the planned titles in well under a second), and relaunches the app in the
--- background with `open -g`, which does not steal focus.
---
--- The app's quick window is a non-activating panel, so "leaving the app" is
--- not an event. The app saving the snippet file is the only reliable signal,
--- and that is what this Spoon watches.
---
--- Titles the tool wrote are regenerated when the body changes. A title the
--- person typed is never touched. That bookkeeping lives in the Python side
--- (bin/snippetslab-autotitle); this file only watches, debounces, and
--- sequences quit → apply → relaunch.
---
--- Download: https://github.com/insoul/SnippetsLabAutoTitle.spoon

local obj = {}
obj.__index = obj

obj.name = "SnippetsLabAutoTitle"
obj.version = "0.2"
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
obj.quietSeconds = 30          -- plan titles after this much silence
obj.applyIdleSeconds = 300     -- quit → apply → relaunch only after this much silence
obj.applyCheckSeconds = 60
obj.logger = hs.logger.new("SLAutoTitle", "info")

local task, rerun, quietTimer, applyTimer
local lastEvent = 0
local applyPending = false

local function lastLine(s)
    local last
    for line in (s or ""):gmatch("[^\n]+") do last = line end
    return last
end

local function summaryOf(self, code, out, err)
    if code ~= 0 then
        self.logger.e("tool exit " .. tostring(code) .. ": " .. (err or ""))
        return nil
    end
    local line = lastLine(out)
    self.logger.i(line or "no summary")
    return hs.json.decode(line or "") or {}
end

-- One tool process at a time. `mode` is "plan" or "apply"; `done(summary)` runs
-- after the process exits (summary is nil when the tool failed).
local function runTool(self, mode, done)
    if task then return false end
    local args = { "--library", self.library }
    if mode == "apply" then table.insert(args, "--apply") end
    task = hs.task.new(self.tool, function(code, out, err)
        task = nil
        local ok, e = pcall(function()
            local summary = summaryOf(self, code, out, err)
            if done then done(summary) end
        end)
        if not ok then self.logger.e(tostring(e)) end
    end, args)
    if not task then
        self.logger.e("cannot spawn " .. tostring(self.tool))
        return false
    end
    task:start()
    return true
end

local function armApply(self)
    if applyTimer then return end
    applyTimer = hs.timer.doEvery(self.applyCheckSeconds, function()
        local ok, e = pcall(function() self:_tryApply() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
end

local function disarm()
    if applyTimer then applyTimer:stop(); applyTimer = nil end
end

local function afterPlan(self, summary)
    if summary and (summary.planned or 0) > 0 then
        applyPending = true
        armApply(self)
    end
    if rerun then rerun = false; self:_plan() end
end

function obj:_plan()
    local started = runTool(self, "plan", function(summary) afterPlan(self, summary) end)
    if not started then rerun = true end
end

function obj:_onEvent()
    lastEvent = os.time()
    if quietTimer then quietTimer:stop() end
    quietTimer = hs.timer.doAfter(self.quietSeconds, function()
        quietTimer = nil
        local ok, e = pcall(function() self:_plan() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
end

-- Apply the plan, then bring the app back if we quit it. The app is relaunched
-- even when the tool failed: never leave it closed on the person's behalf.
local function applyAndRelaunch(self, relaunch)
    local started = runTool(self, "apply", function(summary)
        if summary and (summary.planned or 0) == 0 then applyPending = false end
        if relaunch then
            -- `open -g` keeps focus where it is. hs.application.launchOrFocus would steal it.
            local t = hs.task.new("/usr/bin/open", nil, { "-g", "-b", self.bundleID })
            if t then t:start() end
            self.logger.i("relaunched")
        end
    end)
    if not started and relaunch then
        local t = hs.task.new("/usr/bin/open", nil, { "-g", "-b", self.bundleID })
        if t then t:start() end
        self.logger.w("apply could not start; relaunched anyway")
    end
end

function obj:_tryApply(force)
    if not applyPending then disarm(); return end
    if task then return end                                   -- a plan is running; next tick
    if not force and os.time() - lastEvent < self.applyIdleSeconds then return end
    local app = hs.application.get(self.bundleID)
    if not app then
        -- Not running: nothing to reconcile with, write now.
        self.logger.i("applying (app not running)")
        applyAndRelaunch(self, false)
        return
    end
    if not force and not app:isHidden() and #app:visibleWindows() > 0 then return end

    local pid = app:pid()
    self.logger.i("quitting SnippetsLab to apply")
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
                self.logger.w("SnippetsLab did not quit within 10s; will retry")
                return
            end
            applyAndRelaunch(self, true)
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
--- Stop watching and cancel pending timers. A plan left in the state file is
--- applied the next time the Spoon runs.
function obj:stop()
    if self.watcher then self.watcher:stop(); self.watcher = nil end
    if quietTimer then quietTimer:stop(); quietTimer = nil end
    disarm()
    if task then task:terminate(); task = nil end
    rerun = false
    applyPending = false
    return self
end

--- SnippetsLabAutoTitle:runNow()
--- Method
--- Plan immediately, without waiting for the quiet period.
function obj:runNow()
    local ok, e = pcall(function() self:_plan() end)
    if not ok then self.logger.e(tostring(e)) end
    return self
end

--- SnippetsLabAutoTitle:applyNow()
--- Method
--- Quit the app, apply the plan and relaunch, ignoring the idle and hidden
--- conditions. For trying it out by hand.
function obj:applyNow()
    applyPending = true
    local ok, e = pcall(function() self:_tryApply(true) end)
    if not ok then self.logger.e(tostring(e)) end
    return self
end

return obj
