# 8A 안정성·복구 재검증 — 0.8.0

2026-11-17, 중단된 작업 상태부터 확인했습니다. 당시 작성한 회귀 검사만 남아 있었고 제품 수정은 적용되지 않았습니다. 실제 사용자 데이터/키/계정과 원본 사진 27개는 사용하거나 변경하지 않았습니다.

## 재현과 수정

| 구분 | 재현된 문제와 수정 |
|---|---|
| 알림 트랜잭션 | `NotificationService.poll()`이 connection context로 바깥 작업을 먼저 커밋하고 알림도 즉시 발행할 수 있었음. 공통 `Store.transaction()`에 참여하고 전체 확정 후 묶음 발행. 취소 시 마지막 조회 시각도 복구 |
| 중복 실행 통신 | 무응답 연결의 수/수명·요청 크기를 제한하지 않았음. 사용자 단위 로컬 채널에 최대 8개·2초·읽기 버퍼 5바이트 적용. 고정 `show`/`ok`만 처리하고 연결·기한 타이머·버퍼 정리 |
| Qt 수명 | 이전 3회에서 QApplication 소유 타이머가 1→2→3개, 앱 객체도 누적. 트레이/클릭 타이머와 내부 서비스의 소유권을 창에 연결하고 활성화 신호 해제. 상태/말투 콜백의 강한 자기 참조를 약한 참조로 변경 |

외부에서 주입한 키 서비스와 실행 잠금은 호출자의 소유권을 유지합니다. 실제 그림·말투 규칙·과거 대화는 바꾸지 않았습니다. 스키마 7과 `%LOCALAPPDATA%\DesktopBuddy` 위치도 유지합니다.

주요 파일은 `services/notification_service.py`, `services/single_instance.py`, `app.py`, `services/chat_service.py`, `ui/pet.py`, `tests/test_stability.py`, `tools/stability_smoke.py`입니다.

## 회귀 검증

신규 13개는 별도 프로세스의 정상/정리 없는 종료 뒤 DB 재개방·타이머 체크포인트·미커밋 계획 롤백, 알림의 전체 확정/취소·조회 시각 복구·재개방 중복 방지, 제한된 로컬 통신·잠금 재획득, 반복 객체 해제, 종료 체크포인트 실패 시 잠금/DB 정리를 포함합니다.

최초 9개는 5개 통과·4개 실패했습니다. 같은 원인의 검사가 포함되어 실패 수와 결함 종류는 다릅니다. 정상 종료 7초/정리 없는 종료의 마지막 5초를 보존하고 재개방 사이 공백은 집중 시간에 넣지 않는 것을 확인했습니다. SQLite quick_check/foreign_key_check도 검사합니다. AI/파일 작업의 취소·지연 응답·닫기는 기존 회귀에 포함합니다. 전체·Windows Qt·화면·빌드 수치는 [현재 검증 기록](TEST_REPORT.md)을 따릅니다.

## 반복 실행 측정

Windows Qt의 `tools/stability_smoke.py --cycles 20`은 고유 `.qa/stability/<UUID>`의 기본 캐릭터·시험 할 일·진행 집중 하나로 반복합니다. 메모리 대체 키/HTTP 금지 대체 클라이언트를 사용하며 실제 사용자 DB 경로를 입력받지 않습니다.

| 항목 | 관찰 결과 |
|---|---|
| 반복 | 20회 통과. 앱·프레임 소유 객체·앱 소유 타이머·buddy 작업 스레드 잔존 각각 0 |
| 실제 시간 | 벽시계 약 47.40초, 프로세스 CPU 약 44.80초. 시작/종료 부하이며 평상시 대기 CPU가 아님 |
| 작업 집합 | 3~20회 98,947,072~122,454,016바이트. 마지막 120,217,600바이트(약 114.65 MiB) |
| 핸들 | 3~20회 358~370개, 마지막 370개. OS/Qt 자원도 포함하므로 0개 기준이 아님 |
| 합성 시계 | 집중 60초 보존. 회차 사이 합성 1시간 공백은 집중에 추가하지 않음. 실제 20시간 시험이 아님 |

초기 UI 이벤트 처리 전에 창을 파기한 시험 경로에서는 메모리 누적을 관찰했습니다. 이를 정상 실행의 사용량으로 제시하지 않았습니다. 도구가 실제 이벤트 루프처럼 초기 레이아웃/큐를 처리하도록 맞추고, 프레임 소유 객체의 해제까지 검증한 뒤 위 수치를 측정했습니다.

메모리는 [GetProcessMemoryInfo](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo)의 [PROCESS_MEMORY_COUNTERS](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters), 핸들은 [GetProcessHandleCount](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesshandlecount)로 시험 프로세스 자체만 읽습니다. 다른 앱을 조사하거나 결과를 전송하지 않습니다.

## 실행·남은 확인

트레이에서 종료 후 먼작귀 바로가기 또는 `run_windows.bat`으로 다시 실행합니다. 개발 검사는 다음과 같습니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe tools\stability_smoke.py --cycles 20
```

반복 도구는 기본 offscreen이며 해당 프로세스의 `QT_QPA_PLATFORM=windows`로 Windows Qt를 선택할 수 있습니다. 자신의 새 QA 폴더만 사용합니다.

짧은 반복·가속 시계·대체 HTTP 검사이며 수시간/수일 실사용, 실제 OS 종료/절전/복귀/시계 변경·키보드/IME/스크린리더·토스트/트레이·혼합 DPI·Windows 10·실제 API/과금·외부 파일 인수는 남습니다. 이전 EXE가 Windows 앱 제어에 차단돼 이번 EXE도 실행 미검증입니다. 정책 변경/우회는 하지 않았습니다. 모든 오류가 없다는 보장은 하지 않습니다.

다음 기능은 수동 백업·복원 등 DATA-UX이며, 실제 장치/배포·장시간 인수는 [수동 목록](MANUAL_TESTS.md)에서 구분합니다.
