# snippetslab-autotitle 설계

SnippetsLab 에서 제목 없이 저장한 스니펫에 LM Studio 로 만든 제목을 자동으로 넣는다.

## 목표

- 새 스니펫이 `untitled snippet` 인 채로 남지 않게 한다.
- 도구가 넣은 제목은 본문이 바뀌면 다시 만든다.
- 사용자가 직접 쓴 제목은 절대 바꾸지 않는다.
- 사용자의 포커스·선택·창 상태를 방해하지 않는다.

## 제약 (스파이크로 확인, 2026-09-10 ~ 09-15)

- SnippetsLab 2.6.4 는 AppleScript 사전이 없다. 번들 CLI `lab` 은 읽기 전용이다.
- 라이브러리는 iCloud 안의 파일 패키지다. 스니펫 하나가 NSKeyedArchiver binary plist 파일 하나다.
  `~/Library/Mobile Documents/iCloud~com~renfei~SnippetsLab/main.snippetslablibrary/Database/Snippets/<UUID>.data`
- 앱은 시작할 때 패키지를 임시 디렉토리(`NSIRD_SnippetsLab_*`)로 복사해 메모리에 올린다. 이후 로컬 파일 변경은 읽지 않는다. 일반 쓰기와 NSFileCoordinator 조정 쓰기 모두 실행 중인 앱에 반영되지 않는다. 앱은 iCloud 가 서버에서 내려받은 변경만 듣는다.
- 앱은 저장할 때마다 패키지 전체를 NSFileWrapper 로 다시 쓴다. 캐시와 같은 파일은 하드링크로 넘기고, **캐시와 다른 파일은 캐시의 바이트로 되돌린다**(원본 mtime·birth 까지 복원). 그래서 앱이 실행 중일 때 외부에서 쓴 제목은 앱의 다음 저장 때 사라진다(2026-09-15 17:16 실측, 11개 복귀). 앱을 닫은 상태에서 쓰고 다시 띄우면 앱이 디스크를 읽어 캐시를 만들므로 유지된다(같은 날 17:23 실측, 사용자 편집·재실행 후에도 유지).
- 앱은 노트를 옮기면 곧바로 그 스니펫 파일을 쓴다. 앱을 떠나는 시점과 무관하다.
- 단축키로 여는 창은 앱을 활성화하지 않는 패널이다. SnippetsLab 은 frontmost 가 되지 않으므로 "앱을 떠나는 순간" 은 이벤트로 존재하지 않는다.
- `quit` 후 `open -g -b com.renfei.SnippetsLab` 은 포커스를 뺏지 않고 숨김 상태를 유지한다.
- AX 로 제목 필드에 값을 넣으려면 앱을 활성화하고 Return 을 보내야 한다. 사용자의 포커스 이동을 되돌리므로 쓰지 않는다.
- 새 스니펫의 기본 제목은 문자열 `untitled snippet` 이다. 제목 필드의 placeholder 도 같은 문자열이다.

## 구성 요소

IMEHint.spoon 과 같은 구조다. Spoon 하나가 독립 git 리포이고, 감시·재실행은 Lua, 파일 편집·LM 호출은 Python 이 맡는다.

| 항목 | 경로 |
|---|---|
| Spoon | `~/.hammerspoon/Spoons/SnippetsLab.spoon/` (독립 git 리포) |
| Lua | `…/SnippetsLab.spoon/autotitle.lua` — 감시, 디바운스, 종료→적용→재실행 순서. `init.lua` 는 기능 모듈을 `spoon.SnippetsLab.<기능>` 으로 매다는 허브 |
| Python | `…/SnippetsLab.spoon/bin/snippetslab-autotitle` — 판정, 생성(계획), 파일 쓰기(적용) (Python 3, 표준 라이브러리만) |
| 실행 링크 | `~/.local/bin/snippetslab-autotitle` (수동 실행용) |
| 로드 | `~/.hammerspoon/init.lua` 에서 `hs.loadSpoon("SnippetsLab"):start()` |
| 설계 문서 | `…/SnippetsLab.spoon/docs/design.md` (이 문서) |
| 상태 | `~/.local/state/snippetslab-autotitle/state.json` |
| 로그 | `~/.local/state/snippetslab-autotitle/log` |
| 설정 | `~/.config/snippetslab-autotitle/config.json` (없으면 기본값) |

## 동작

### 1. 트리거 (Lua)

`hs.pathwatcher` 가 `Snippets/` 디렉토리를 본다. 이벤트가 올 때마다 30초 타이머를 다시 시작한다. 타이머가 만료되면(30초간 조용하면) `hs.task` 로 Python 을 **계획 모드**로 한 번 실행한다. 계획 모드는 판정과 제목 생성만 하고 결과를 상태 파일의 `planned` 에 쌓는다. 파일은 건드리지 않는다. Python 이 도는 동안 이벤트가 오면 끝난 뒤 한 번 더 실행한다. 동시에 두 개는 돌리지 않는다.

Python 은 각 파일의 mtime 을 상태 파일의 `last_run` 과 비교해 그 뒤에 바뀐 파일만 후보로 삼는다. 안전장치로 최근 10초 안에 바뀐 파일은 건너뛴다.

### 2. 판정

상태 파일은 `UUID → {auto_title, content_hash}` 이다. `content_hash` 는 모든 파트의 content 를 이어 붙인 SHA-1 이다.

| 현재 제목 | 기록 | 동작 |
|---|---|---|
| `untitled snippet` | 무관 | 생성 |
| 기록된 `auto_title` 과 같음 | 해시 같음 | 무시 (도구 자신의 쓰기 포함) |
| 기록된 `auto_title` 과 같음 | 해시 다름 | 재생성 |
| 그 외 | 기록 있음 | 사용자 제목. 기록을 지우고 잠금 |
| 그 외 | 기록 없음 | 사용자 제목. 무시 |

잠긴 스니펫은 사용자가 제목을 지워 `untitled snippet` 으로 돌아가면 다시 대상이 된다.

상태 파일이 없으면 모든 현재 제목을 사용자 제목으로 본다. 실패는 항상 "건드리지 않는" 쪽이다.

본문이 비어 있거나 공백뿐이면 생성하지 않는다.

### 3. 생성

LM Studio `POST http://localhost:1234/v1/chat/completions` 을 호출한다.

- 모델 id 는 설정값이다. 기본값은 `qwen/qwen3.6-35b-a3b`.
- 본문은 앞에서 4000자까지만 보낸다.
- 시스템 프롬프트: 본문의 언어로, 40자 이내, 따옴표·마침표·줄바꿈 없이 제목 한 줄만 답한다.
- 응답을 다듬는다: 앞뒤 공백·따옴표 제거, 첫 줄만, 40자 초과는 자른다. 결과가 비면 생성 실패로 본다.
- 타임아웃 60초. 실패하면 로그에 남기고 그 스니펫은 다음 실행에서 다시 본다.

### 4. 반영 (적용 모드, `--apply`)

파일 쓰기는 5단계의 순서 안에서, 앱이 닫힌 동안에만 일어난다. `planned` 의 각 항목에 대해 파일을 다시 읽어 계획 시점의 제목·본문 해시와 같을 때만 쓴다. 다르면(그 사이 사용자가 손댔다) 계획을 버리고 다음 계획 때 다시 판정한다. 파일이 없으면 계획을 버린다. LM 호출은 없다.

`plistlib` 로 파일을 읽어 `SnippetTitle` 이 가리키는 문자열 객체만 바꾸고 `FMT_BINARY` 로 다시 쓴다. 임시 파일에 쓴 뒤 `os.replace` 로 바꾼다. 다른 객체(날짜, 파트, 태그)는 건드리지 않는다. 쓰기 전에 원본을 `~/.local/state/snippetslab-autotitle/backup/<UUID>.<epoch>.data` 로 복사한다. 백업은 스니펫당 최근 3개만 남긴다.

쓴 뒤 상태 파일에 `auto_title` 과 `content_hash` 를 기록하고 `planned` 에서 지운다.

### 5. 종료 → 적용 → 재실행 (Lua)

계획 모드의 요약 JSON 에서 `planned > 0` 이면 Lua 가 `applyPending = true` 로 두고 60초 간격 타이머로 조건을 본다.

- 마지막 pathwatcher 이벤트로부터 5분이 지났다. 이벤트가 계속 오면 5분은 그때마다 처음부터 센다. 그동안 30초 계획은 계속 돌아 `planned` 가 쌓인다.
- 앱이 숨겨져 있거나(`app:isHidden()`) 보이는 창이 없다(`#app:visibleWindows() == 0`).
- Python 이 지금 돌고 있지 않다.

조건이 맞으면 `app:kill()` 로 앱을 종료하고 프로세스가 사라질 때까지 최대 10초 기다린 뒤, Python 을 `--apply` 로 실행해 `planned` 를 파일에 쓰고, `hs.task` 로 `/usr/bin/open -g -b <bundleID>` 를 실행해 앱을 백그라운드로 다시 띄운다. `hs.application.launchOrFocus` 는 포커스를 가져오므로 쓰지 않는다. 적용이 실패해도 앱은 다시 띄운다. 앱이 꺼져 있는 시간은 2~3초다. 앱이 원래 안 떠 있었으면 종료·재실행 없이 `--apply` 만 한다. 앱이 10초 안에 안 꺼지면 다음 타이머에서 다시 본다.

적용 후 `planned` 가 비면 `applyPending = false`. 적용 자체가 만드는 파일 이벤트는 다음 계획에서 "자동 제목·해시 같음 → 무시" 로 끝난다.

### 6. 로그

한 줄에 시각, UUID 앞 8자, 동작(plan / apply / lock / skip-changed / skip-gone / error), 제목. 로그 파일은 1MB 를 넘으면 `.1` 로 돌린다. 판정 결과가 skip 인 경우는 소음을 피하려고 남기지 않는다(적용 단계의 skip-changed·skip-gone 은 남긴다). relaunch 는 Python 로그가 아니라 Hammerspoon 콘솔(hs.logger)에 남는다.

## 명령행

```
snippetslab-autotitle            # 계획: 바뀐 파일을 판정·생성해 planned 에 쌓고 JSON 요약을 출력 (파일 쓰기 없음)
snippetslab-autotitle --apply    # 적용: planned 를 파일에 쓴다. 앱이 닫힌 상태에서만 (Lua 가 순서를 맡는다)
snippetslab-autotitle --all      # last_run 을 무시하고 모든 파일을 본다 (초기 적용용)
snippetslab-autotitle --dry-run  # 판정과 생성만 하고 상태를 저장하지 않는다
snippetslab-autotitle --status   # 상태 파일과 잠금·계획 목록을 보여 준다
snippetslab-autotitle --unlock <UUID>  # 잠금을 풀어 다음 실행에서 다시 생성하게 한다
```

## 테스트

- 단위: plist 읽기/쓰기가 제목 외의 객체를 바꾸지 않는다 (바이트 단위 비교는 하지 않고 객체 비교). 판정 표의 다섯 행. 응답 다듬기.
- 통합: 스파이크에서 쓴 스니펫 `134DB659…` 를 대상으로 `--dry-run`, 실제 쓰기, 재실행 후 `lab search --title-only` 로 확인.
- Lua: Hammerspoon 콘솔에서 `spoon.SnippetsLab.autotitle:runNow()` 로 Python 호출과 JSON 파싱을 확인. 재실행 조건은 창을 열어 둔 상태와 닫은 상태에서 각각 확인.
- LM Studio 호출은 `--dry-run` 으로 프롬프트 품질을 먼저 본다.

## 하지 않는 것

- 편집 시간(`SnippetDateModified`) 보존. 파일 직접 쓰기는 이 값을 건드리지 않으므로 별도 처리가 필요 없다.
- 앱 실행 중 파일 쓰기. 앱의 다음 저장 때 되돌아가므로 하지 않는다.
- 태그·폴더·본문 변경.
- setapp 라이브러리(`iCloud~com~renfei~SnippetsLab-setapp`) 지원. 현재 비어 있다.
