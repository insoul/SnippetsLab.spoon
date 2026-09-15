# SnippetsLabAutoTitle.spoon

SnippetsLab 에서 제목 없이 저장한 스니펫에 LM Studio 로 만든 제목을 넣는다.

- 도구가 넣은 제목은 본문이 바뀌면 다시 만든다.
- 사용자가 직접 쓴 제목은 바꾸지 않는다.
- 포커스·선택·창 상태를 건드리지 않는다. 제목은 30초 조용할 때 미리 만들어 두고(계획), 앱이 숨겨져 있거나 보이는 창이 없고 5분간 조용할 때 앱을 잠깐 닫고 써 넣은 뒤(적용, 1초 안팎) 백그라운드로 다시 띄운다. SnippetsLab 은 저장할 때마다 자기 캐시로 파일을 되돌리므로 파일은 앱이 닫힌 동안에만 쓴다.

왜 이런 모양인지는 `docs/design.md` 에 있다.

## 설치

```sh
git clone https://github.com/insoul/SnippetsLabAutoTitle.spoon ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon
ln -sfn ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon/bin/snippetslab-autotitle ~/.local/bin/snippetslab-autotitle
```

`~/.hammerspoon/init.lua`:

```lua
hs.loadSpoon("SnippetsLabAutoTitle"):start()
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
PYTHONPATH=lib:tests /usr/bin/python3 -m unittest discover -s tests -v
```
