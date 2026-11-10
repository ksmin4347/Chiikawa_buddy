# 로컬 빌드·배포 후보 — 0.5.9

0.5.9는 ZIP 생성과 무결성 검증까지 확인한 로컬 배포 후보입니다. 이전 0.5.8 EXE가 이 PC의 Windows 앱 제어 정책에 막혔으며, 이번에는 소스의 Windows Qt 검사를 수행했습니다. 0.5.9 EXE 실제 실행·Windows 10·Python 없는 깨끗한 PC·기존 데이터 업데이트 인수는 남아 있습니다. 현재 확인된 실행 경로는 바탕화면 먼작귀 또는 `run_windows.bat`입니다.

## 만들기

프로젝트 루트에서 `build_windows.bat`을 실행합니다. 테스트 → PyInstaller → 번들 검사 → ZIP 생성/해시 검증 순서이며 중간 실패 시 성공으로 표시하지 않습니다.

생성 파일:

- `dist\DesktopBuddy\DesktopBuddy.exe`와 `_internal` 폴더
- `dist\releases\Meonjakgwi-0.5.9-windows-x64.zip`
- 같은 위치의 `Meonjakgwi-0.5.9-windows-x64.zip.sha256`

ZIP에는 `DesktopBuddy` 폴더 아래 실행 파일·런타임·고정 캐릭터/음악/아이콘·`사용법.txt`·`파일목록.json`이 들어갑니다. 파일 목록에는 각 파일의 상대 경로·크기·SHA-256을 기록합니다. 사용자 DB·로그·작업 원본·QA·개발 환경은 제외하며 앱 데이터 폴더를 읽거나 초기화하지 않습니다. 인터넷 업로드나 GitHub Release 게시를 수행하지 않습니다.

## 다시 검증하기

개발 환경에서는 다음 명령으로 압축을 풀지 않고 파일 목록/크기/해시와 ZIP 체크섬을 검증합니다.

```powershell
.\.venv\Scripts\python.exe tools\package_release.py --verify dist\releases\Meonjakgwi-0.5.9-windows-x64.zip
```

Python 없이 ZIP 자체의 해시만 확인하려면 PowerShell에서 실행합니다.

```powershell
Get-FileHash .\Meonjakgwi-0.5.9-windows-x64.zip -Algorithm SHA256
Get-Content .\Meonjakgwi-0.5.9-windows-x64.zip.sha256
```

두 값이 같은지 비교합니다. SHA-256 일치는 파일 변형 여부 확인이며 코드 서명이나 실행 검증을 대신하지 않습니다. 파일 수정/재빌드 시 값은 바뀔 수 있으므로 같은 빌드에서 만든 체크섬과 비교합니다.

## 실행과 업데이트

ZIP 전체를 새 폴더에 압축 해제합니다. `DesktopBuddy.exe`와 `_internal`을 함께 두고 EXE를 실행합니다. EXE만 복사하거나 ZIP 내부에서 바로 실행하지 않습니다. 정책이 실행을 차단하면 해당 상태를 기록하고 실행 성공으로 처리하지 않습니다. 이 작업에서 Windows 보안 설정은 변경하지 않았습니다.

업데이트 전 트레이의 **프로그램 종료**를 누릅니다. 새 폴더의 프로그램도 기존 `%LOCALAPPDATA%\DesktopBuddy`를 사용합니다. 데이터 폴더를 지우거나 덮어쓰지 않습니다. 정상 실행·계획·캐릭터·집중 복구의 실제 장치 확인은 [수동 목록](MANUAL_TESTS.md)을 따릅니다.

빌드 DLL 오류 원인과 이번 검증 범위는 [0.5.8 검토 기록](AUDIT_REPORT_0.5.8.md)에 있습니다.

긴 경로 수정과 Windows Qt 키보드/배율 검증은 [0.5.9 검토 기록](AUDIT_REPORT_0.5.9.md)에 있습니다. 실제 OS 입력/IME와 EXE 실행 성공으로 확대 해석하지 않습니다.
