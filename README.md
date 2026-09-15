# SnippetsLabAutoTitle.spoon

SnippetsLab 에서 제목 없이 저장한 스니펫에 LM Studio 로 만든 제목을 넣는다.

- 도구가 넣은 제목은 본문이 바뀌면 다시 만든다.
- 사용자가 직접 쓴 제목은 바꾸지 않는다.
- 포커스·선택·창 상태를 건드리지 않는다. 앱이 숨겨져 있고 5분간 조용할 때만 백그라운드로 재실행한다.

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
snippetslab-autotitle            # 바뀐 파일을 처리 (Spoon 이 부르는 기본 동작)
snippetslab-autotitle --all      # 모든 파일을 본다 (처음 적용할 때)
snippetslab-autotitle --dry-run  # 쓰지 않고 판정·생성만
snippetslab-autotitle --status   # 상태와 잠금 목록
snippetslab-autotitle --unlock <UUID>   # 잠금을 풀고 다음 실행에서 다시 생성
```

상태·로그·백업은 `~/.local/state/snippetslab-autotitle/` 에 있다.

## 테스트

```sh
PYTHONPATH=lib:tests /usr/bin/python3 -m unittest discover -s tests -v
```
