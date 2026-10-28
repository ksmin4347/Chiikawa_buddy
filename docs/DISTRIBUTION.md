# 초기 Windows 빌드

`build_windows.bat`은 자동 테스트 후 PyInstaller로 `dist\DesktopBuddy`를 만듭니다. 현재 버전은 0.1.0이며 앱 아이콘과 Windows 파일 버전 리소스를 포함합니다.

현재 PC의 Windows 앱 제어 정책이 새 EXE의 실행을 차단했습니다. 빌드는 성공했지만 EXE의 실제 실행은 미검증입니다. 정책을 변경하거나 우회하지 않았습니다. 현재 PC에서는 `run_windows.bat`으로 개발 실행본을 사용하세요.

## 폴더형 실행

- 실행 파일: `dist\DesktopBuddy\DesktopBuddy.exe`.
- Python 런타임, Qt DLL/플러그인, 기본 캐릭터 프레임은 `_internal`에 포함됩니다.
- DesktopBuddy 폴더 전체를 전달해야 합니다. EXE 하나만 전달하지 않습니다.
- Python이나 VS Code 없이 실행하도록 패키징했지만 깨끗한 별도 PC에서의 최종 검증은 아직입니다.
- 설정·위치는 설치 폴더가 아닌 `%LOCALAPPDATA%\DesktopBuddy`에 남습니다.
- 코드 서명과 설치 프로그램은 아직 제공하지 않습니다.

## 설치형과 차이

현재는 압축을 풀거나 폴더를 복사해 실행하는 방식입니다. 시작 메뉴/바로가기/제거 프로그램/자동 업데이트를 등록하지 않습니다. Windows 시작 시 자동 실행도 등록하지 않습니다. 설치 프로그램과 단일 파일 빌드는 PHASE 8 안정화 이후 검토합니다.

## 재현

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm DesktopBuddy.spec
```

명시적인 spec 파일에 에셋, Qt 의존성, Windows 아이콘/버전을 고정했습니다. WebEngine/QML/PDF 모듈을 앱에서 사용하지 않으므로 제외합니다. 런타임 요구사항은 PySide6-Essentials이고 테스트/빌드 도구는 개발 의존성입니다.

배포 전에는 전체 수동 체크리스트, Windows 10/11, 여러 DPI와 모니터, 절전, 기존 DB 유지, 정상 종료, 오류 로그, 장시간 리소스 사용을 확인해야 합니다. 초기 EXE가 생성되었다는 사실만으로 정식 배포 검증 완료를 뜻하지 않습니다.
