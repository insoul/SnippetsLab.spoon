--- === SnippetsLab.capture ===
---
--- Save the front app's selected text (or, failing that, the clipboard) as a
--- new SnippetsLab snippet, with a title and language from a local LLM.
--- Loaded by SnippetsLab.spoon/init.lua as `spoon.SnippetsLab.capture`.
---
--- Saving goes through SnippetsLab 2.7's `lab create`, so the app stays open
--- and no library file is touched. `lab` can only create snippets, never edit
--- them, which is why the title has to be right at creation time: a snippet
--- saved this way never enters autotitle's quit → apply → relaunch cycle.
---
--- The LLM call and the `lab` call run in the Python tool
--- (bin/snippetslab-capture) so the hotkey returns at once; the result shows
--- up as an alert a few seconds later.
---
--- Download: https://github.com/insoul/SnippetsLab.spoon

local obj = {}
obj.__index = obj

obj.name = "SnippetsLab.capture"
obj.version = "0.1"
obj.author = "insoul <insoo.jung+github@gmail.com>"
obj.homepage = "https://github.com/insoul/SnippetsLab.spoon"
obj.license = "MIT - https://opensource.org/licenses/MIT"

local function scriptPath()
    return debug.getinfo(2, "S").source:sub(2):match("(.*/)")
end
obj.spoonPath = scriptPath()

--- SnippetsLab.capture.hotkey
--- Variable
--- {mods, key} bound by start(). Set before start() to change it.
obj.hotkey = { { "alt" }, "c" }

--- SnippetsLab.capture.lab
--- Variable
--- Path of SnippetsLab's `lab` command-line tool.
obj.lab = "/Applications/SnippetsLab.app/Contents/Helpers/lab"

--- SnippetsLab.capture.folder
--- Variable
--- Folder (name or UUID) to file new snippets in; nil for the library root.
--- The folder must already exist in SnippetsLab: `lab` cannot create folders,
--- and when the folder is missing the snippet is saved at the root instead.
obj.folder = "Clipboard"

obj.logger = hs.logger.new("SLCapture", "info")

local task

local function lastLine(s)
    local last
    for line in (s or ""):gmatch("[^\n]+") do last = line end
    return last
end

-- The selection is read through accessibility, not by faking ⌘C, so the
-- clipboard is left alone when there is a selection. Apps that expose no
-- AXSelectedText (some Electron views, terminals) fall through to the clipboard.
local function textToSave()
    local ok, el = pcall(hs.uielement.focusedElement)
    if ok and el then
        local ok2, sel = pcall(function() return el:selectedText() end)
        if ok2 and type(sel) == "string" and sel:match("%S") then return sel, "selection" end
    end
    local clip = hs.pasteboard.getContents()
    if clip and clip:match("%S") then return clip, "clipboard" end
    return nil
end

--- SnippetsLab.capture:capture()
--- Method
--- Save the selected text or clipboard now. Bound to the hotkey by start().
function obj:capture()
    if task then
        hs.alert.show("SnippetsLab: 아직 저장 중")
        return self
    end
    local text, source = textToSave()
    if not text then
        hs.alert.show("SnippetsLab: 저장할 텍스트가 없다")
        return self
    end
    hs.alert.show("SnippetsLab 에 저장 중… (" .. (source == "selection" and "선택 영역" or "클립보드") .. ")", 1.5)
    task = hs.task.new(self.tool, function(code, out, err)
        task = nil
        local line = lastLine(out)
        local result = line and hs.json.decode(line)
        if type(result) ~= "table" then
            self.logger.e("no result from tool (exit " .. tostring(code) .. "): " .. tostring(err))
            hs.alert.show("SnippetsLab 저장 실패: 도구 오류 (콘솔 참고)", 3)
            return
        end
        if result.error then
            self.logger.e(result.error)
            hs.alert.show("SnippetsLab 저장 실패: " .. result.error, 4)
            return
        end
        self.logger.i(line)
        local where = result.folder and (" → " .. result.folder)
            or (self.folder and " → 루트 (폴더 '" .. self.folder .. "' 없음)" or "")
        local tags = ""
        for _, t in ipairs(result.tags or {}) do tags = tags .. " #" .. t end
        hs.alert.show("SnippetsLab 저장됨: " .. result.title
            .. (result.language and (" (" .. result.language .. ")") or "") .. where .. tags, 2.5)
    end, self.folder and { "--lab", self.lab, "--folder", self.folder } or { "--lab", self.lab })
    if not task then
        self.logger.e("cannot spawn " .. tostring(self.tool))
        hs.alert.show("SnippetsLab 저장 실패: 도구를 띄우지 못함", 3)
        return self
    end
    -- setInput must precede start(): input set after start is discarded (hs.task docs, verified with /bin/cat)
    task:setInput(text)
    if not task:start() then
        task = nil
        self.logger.e("cannot start " .. tostring(self.tool))
        hs.alert.show("SnippetsLab 저장 실패: 도구를 띄우지 못함", 3)
        return self
    end
    task:closeInput()
    return self
end

function obj:init()
    if not self.tool then
        self.tool = self.spoonPath .. "bin/snippetslab-capture"
    end
    return self
end

--- SnippetsLab.capture:start()
--- Method
--- Bind the hotkey. Returns the Spoon object.
function obj:start()
    self:stop()
    self.key = hs.hotkey.bind(self.hotkey[1], self.hotkey[2], "SnippetsLab 에 저장", function()
        local ok, e = pcall(function() self:capture() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
    return self
end

--- SnippetsLab.capture:stop()
--- Method
--- Unbind the hotkey and abandon a save in progress.
function obj:stop()
    if self.key then self.key:delete(); self.key = nil end
    if task then task:terminate(); task = nil end
    return self
end

return obj
