# SnippetsLab.spoon

SnippetsLab 을 위한 Hammerspoon 기능 모음. 기능 하나가 모듈 하나이고 `spoon.SnippetsLab.<기능>` 으로 드러난다.

## autotitle

SnippetsLab 에서 제목 없이 저장한 스니펫에 LM Studio 로 만든 제목을 넣는다.

- 도구가 넣은 제목은 본문이 바뀌면 다시 만든다.
- 사용자가 직접 쓴 제목은 바꾸지 않는다.
- 포커스·선택·창 상태를 건드리지 않는다. 제목은 30초 조용할 때 미리 만들어 두고(계획), 앱이 숨겨져 있거나 보이는 창이 없고 5분간 조용할 때 앱을 잠깐 닫고 써 넣은 뒤(적용, 1초 안팎) 백그라운드로 다시 띄운다. SnippetsLab 은 저장할 때마다 자기 캐시로 파일을 되돌리므로 파일은 앱이 닫힌 동안에만 쓴다.

왜 이런 모양인지는 `docs/design.md` 에 있다.

## capture

**⌥C** — 앞 앱의 선택 텍스트(없으면 클립보드)를 새 스니펫으로 저장한다. 제목과 언어는 LM Studio 에
한 번에 묻고, 저장은 SnippetsLab 2.7 의 `lab create` 로 한다. 앱은 열린 채 그대로고 라이브러리
파일은 건드리지 않는다. 몇 초 뒤 `SnippetsLab 저장됨: <제목> (<언어>)` alert 가 뜬다.

- 선택 텍스트는 접근성(AXSelectedText)으로 읽는다 — ⌘C 를 흉내 내지 않으므로 클립보드는 그대로다.
  선택을 안 내주는 앱(일부 Electron 뷰, 터미널)에서는 클립보드로 넘어간다.
- 제목이 처음부터 붙으므로 이 경로로 저장한 스니펫은 autotitle 의 "앱 닫고 파일 고치기"를 타지 않는다.
- `lab` 은 새 스니펫만 만들 수 있고 기존 것은 못 고친다(매뉴얼). 그래서 autotitle 은 그대로 남는다.
- SnippetsLab 설정 → Integrations → AI Agents & Command Line Tools 에서 **Write Access** 가 켜져 있어야 한다.
- **Clipboard** 폴더에 넣는다 (`spoon.SnippetsLab.capture.folder`, `nil` 이면 루트). 폴더는 앱에서 미리 만들어
  둬야 한다 — `lab` 은 폴더를 만들지 못하고, 없으면 루트에 저장하고 alert 에 그렇게 표시한다.
- 언어는 LM 이 고른 별칭이 `lab` 에 거부되면 언어 없이 다시 저장한다.
- **태그**도 같은 호출에서 뽑는다. 보수적으로 — 도구·서비스·주제를 명확히 가리키는 짧은 키워드만, 최대
  3개(`max_tags`), 언어 이름·일반어(code, command…)는 제외, 애매하면 안 붙인다. 없는 태그는 `lab` 이 만든다.
  **제외 목록**은 `~/.config/snippetslab-autotitle/tag-exclude.txt` 에 한 줄에 하나씩 적는다(`#` 주석,
  대소문자 무시). `config.json` 의 `"tag_exclude": [...]` 도 같이 적용된다. `"max_tags": 0` 이면 태그를 뽑지 않는다.

키를 바꾸려면 `start()` 전에 `spoon.SnippetsLab.capture.hotkey = {{"alt","shift"}, "s"}`.
명령행에서도 쓸 수 있다: `pbpaste | bin/snippetslab-capture` → `{"uuid","title","language"}` 또는 `{"error"}`.

## 설치

```sh
git clone https://github.com/insoul/SnippetsLab.spoon ~/.hammerspoon/Spoons/SnippetsLab.spoon
ln -sfn ~/.hammerspoon/Spoons/SnippetsLab.spoon/bin/snippetslab-autotitle ~/.local/bin/snippetslab-autotitle
```

`~/.hammerspoon/init.lua`:

```lua
hs.loadSpoon("SnippetsLab"):start()
```

LM Studio 가 `localhost:1234` 에서 서버 모드로 떠 있어야 한다.

### 처음 실행할 때

라이브러리는 iCloud Drive(`~/Library/Mobile Documents/…`) 안에 있으므로, Spoon을 처음 시작하면 macOS가 "Hammerspoon wants to access files managed by iCloud Drive" 대화상자를 띄운다. Allow를 누를 때까지 Hammerspoon이 막혀 AppleScript와 콘솔이 응답하지 않는다. 이 질문은 한 번만 나오므로 Allow를 누르면 된다. Don't Allow를 눌렀다면 시스템 설정 → 개인정보 보호 및 보안 → 파일 및 폴더 → Hammerspoon에서 다시 켠다.

## 설정

`~/.config/snippetslab-autotitle/config.json` (없으면 기본값):

```json
{
  "model": "qwen/qwen3.6-35b-a3b",
  "base_url": "http://localhost:1234/v1",
  "timeout": 60,
  "max_chars": 4000,
  "max_title_len": 40
}
```

즉시 적용해 보려면 Hammerspoon 콘솔에서 `spoon.SnippetsLab.autotitle:applyNow()`.

## 명령행

```
snippetslab-autotitle            # 계획: 바뀐 파일의 제목을 만들어 쌓아 둔다 (파일 쓰기 없음)
snippetslab-autotitle --apply    # 적용: 쌓인 제목을 파일에 쓴다 — 앱을 닫은 뒤에만
snippetslab-autotitle --all      # 모든 파일을 본다 (처음 적용할 때)
snippetslab-autotitle --dry-run  # 상태를 저장하지 않고 판정·생성만
snippetslab-autotitle --status   # 상태와 잠금·계획 목록
snippetslab-autotitle --unlock <UUID>   # 잠금을 풀고 다음 실행에서 다시 생성
```

상태·로그·백업은 `~/.local/state/snippetslab-autotitle/` 에 있다.

## 테스트

```sh
PYTHONPATH=lib:tests /usr/bin/python3 -m unittest discover -s tests -v   # 85 tests
```
