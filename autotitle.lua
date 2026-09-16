--- === SnippetsLab.autotitle ===
---
--- Give untitled SnippetsLab snippets a title from a local LLM (LM Studio).
--- Loaded by SnippetsLab.spoon/init.lua as `spoon.SnippetsLab.autotitle`.
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
--- Download: https://github.com/insoul/SnippetsLab.spoon

local obj = {}
obj.__index = obj

obj.name = "SnippetsLab.autotitle"
obj.version = "0.2"
obj.author = "insoul <insoo.jung+github@gmail.com>"
obj.homepage = "https://github.com/insoul/SnippetsLab.spoon"
obj.license = "MIT - https://opensource.org/licenses/MIT"

local function scriptPath()
    return debug.getinfo(2, "S").source:sub(2):match("(.*/)")
end
obj.spoonPath = scriptPath()

--- SnippetsLab.autotitle.library
--- Variable
--- Directory that holds one .data file per snippet.
obj.library = os.getenv("HOME")
    .. "/Library/Mobile Documents/iCloud~com~renfei~SnippetsLab/main.snippetslablibrary/Database/Snippets"

obj.bundleID = "com.renfei.SnippetsLab"
obj.quietSeconds = 30          -- plan titles after this much silence
obj.applyIdleSeconds = 300     -- quit → apply → relaunch only after this much silence
obj.applyCheckSeconds = 60
obj.logger = hs.logger.new("SLAutoTitle", "info")

local task, rerun, quietTimer, applyTimer, quitWait, startTimer
local lastEvent = 0
local applyPending = false
local quitting = false        -- we sent kill and are waiting for the app to go away
local forceNext = false       -- applyNow() asked to skip the idle/hidden checks once

local function lastLine(s)
    local last
    for line in (s or ""):gmatch("[^\n]+") do last = line end
    return last
end

-- nil when the tool failed or printed no parseable summary; callers must not
-- change any pending state on nil.
local function summaryOf(self, code, out, err)
    if code ~= 0 then
        self.logger.e("tool exit " .. tostring(code) .. ": " .. (err or ""))
        return nil
    end
    local line = lastLine(out)
    local summary = line and hs.json.decode(line)
    if type(summary) ~= "table" then
        self.logger.e("no summary from tool: " .. tostring(line))
        return nil
    end
    self.logger.i(line)
    return summary
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
    if not task:start() then
        self.logger.e("cannot start " .. tostring(self.tool))
        task = nil
        return false
    end
    return true
end

-- `open -g` keeps focus where it is. hs.application.launchOrFocus would steal it.
local function relaunchApp(self)
    local t = hs.task.new("/usr/bin/open", nil, { "-g", "-b", self.bundleID })
    if t and t:start() then
        self.logger.i("relaunched SnippetsLab")
    else
        self.logger.e("could not relaunch SnippetsLab (open -g -b " .. self.bundleID .. ")")
    end
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
    if summary and not summary.busy then
        if (summary.planned or 0) > 0 then
            applyPending = true
            armApply(self)
        else
            applyPending = false
            forceNext = false
            disarm()
        end
    end
    if rerun then rerun = false; self:_plan() end
end

-- Planning waits while a quit → apply → relaunch sequence is in flight, so the
-- apply never finds the tool busy with a plan (rerun replays it afterwards).
function obj:_plan()
    if task or quitting then rerun = true; return end
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

-- Write the plan while the app is closed, then bring the app back if we quit
-- it. The relaunch happens no matter what the tool did: never leave the app
-- closed on the person's behalf.
local function applyAndRelaunch(self, relaunch)
    local function finish()
        if relaunch then relaunchApp(self) end
        quitting = false
        if rerun then rerun = false; self:_plan() end
    end
    if hs.application.get(self.bundleID) then
        -- Someone opened it between our kill and now. Writing would be undone.
        self.logger.w("SnippetsLab is running again; apply postponed")
        quitting = false
        return
    end
    local started = runTool(self, "apply", function(summary)
        local ok, e = pcall(function()
            if summary and not summary.busy and not summary.app_running
                and (summary.errors or 0) == 0 and (summary.planned or 0) == 0 then
                applyPending = false
                disarm()
            end
        end)
        if not ok then self.logger.e(tostring(e)) end
        finish()
    end)
    if not started then
        self.logger.w("apply could not start")
        finish()
    end
end

function obj:_tryApply(force)
    force = force or forceNext
    if not applyPending then disarm(); return end
    if task or quitting then return end                       -- busy; next tick
    if not force and os.time() - lastEvent < self.applyIdleSeconds then return end
    local app = hs.application.get(self.bundleID)
    if not app then
        forceNext = false
        self.logger.i("applying (app not running)")
        applyAndRelaunch(self, false)
        return
    end
    if not force and not app:isHidden() and #app:visibleWindows() > 0 then return end
    forceNext = false

    -- kill() is a graceful terminate: the app saves on the way out, so a title
    -- typed but not yet on disk lands in the file before --apply re-reads it.
    quitting = true
    self.logger.i("quitting SnippetsLab to apply")
    app:kill()
    local tries = 0
    quitWait = hs.timer.waitUntil(function()
        local ok, e = pcall(function()
            tries = tries + 1
            return hs.application.get(self.bundleID) == nil or tries > 20
        end)
        if not ok then self.logger.e(tostring(e)); return true end
        return e
    end, function()
        quitWait = nil
        local ok, e = pcall(function()
            if hs.application.get(self.bundleID) then
                self.logger.w("SnippetsLab did not quit within 10s; will retry")
                quitting = false
                return
            end
            applyAndRelaunch(self, true)
        end)
        if not ok then
            self.logger.e(tostring(e))
            relaunchApp(self)
            quitting = false
        end
    end, 0.5)
end

--- SnippetsLab.autotitle:init()
--- Method
--- Resolves the bundled tool path. Called for you when the Spoon is loaded.
function obj:init()
    if not self.tool then
        self.tool = self.spoonPath .. "bin/snippetslab-autotitle"
    end
    return self
end

--- SnippetsLab.autotitle:start()
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
    -- A plan left in the state file from before a reload has no event to wake
    -- it; run one plan now so a non-empty plan arms the apply timer.
    startTimer = hs.timer.doAfter(2, function()
        startTimer = nil
        local ok, e = pcall(function() self:_plan() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
    return self
end

--- SnippetsLab.autotitle:stop()
--- Method
--- Stop watching and cancel pending timers. A plan left in the state file is
--- picked up by the next start(). If the app was quit by this Spoon and not
--- yet relaunched, it is relaunched here.
function obj:stop()
    if self.watcher then self.watcher:stop(); self.watcher = nil end
    if quietTimer then quietTimer:stop(); quietTimer = nil end
    if startTimer then startTimer:stop(); startTimer = nil end
    disarm()
    if quitWait then quitWait:stop(); quitWait = nil end
    if task then task:terminate(); task = nil end
    if quitting then relaunchApp(self); quitting = false end
    rerun = false
    applyPending = false
    forceNext = false
    return self
end

--- SnippetsLab.autotitle:runNow()
--- Method
--- Plan immediately, without waiting for the quiet period.
function obj:runNow()
    local ok, e = pcall(function() self:_plan() end)
    if not ok then self.logger.e(tostring(e)) end
    return self
end

--- SnippetsLab.autotitle:applyNow()
--- Method
--- Quit the app, apply the plan and relaunch, ignoring the idle and hidden
--- conditions. For trying it out by hand.
function obj:applyNow()
    applyPending = true
    forceNext = true
    armApply(self)
    local ok, e = pcall(function() self:_tryApply(true) end)
    if not ok then self.logger.e(tostring(e)) end
    return self
end

return obj
