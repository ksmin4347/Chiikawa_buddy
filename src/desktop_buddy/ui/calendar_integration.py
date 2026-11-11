"""Offline calendar capabilities and the dated public Planit review."""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from desktop_buddy.ui.common import button, fit_window, label

CALENDAR_STATUS_TEXT = (
    "로컬 캘린더: 사용 중\n"
    "ICS 파일 교환: 사용 가능 · 직접 선택/확인\n"
    "Planit 직접 연결: 이 앱에서 미지원 · 공식 지원 확인 필요"
)

INTEGRATION_NOTES = """현재 사용할 수 있는 기능

먼작귀의 로컬 캘린더와 할 일은 계정 연결 없이 사용할 수 있어요.
ICS 파일 교환은 직접 고른 파일을 미리 보고, 선택한 항목만 확인 후 가져오거나 저장해요.
반복은 선택한 1~366일의 개별 항목으로 교환해요. 자동 동기화하지 않아요.

Planit 조사 대상

플래닛 - 할 일, 일정, 캘린더 · Planit (KR)
iOS App Store ID: 1603481820
Android: 플래닛 - 쉬운 캘린더 · com.PODO.TODODAY
자료 확인일: 2026-11-11

공식 지원 확인이 필요한 부분

조사한 공개 안내에서는 외부 앱용 API·인증 방식, 캘린더 구독 URL,
ICS 가져오기/내보내기 절차를 확인하지 못했어요.
Planit이 이런 기능을 제공하지 않는다고 단정한 것은 아니에요.
공식 문서와 사용 중인 앱 버전의 확인이 더 필요해요.
먼작귀는 현재 Planit 계정 연결·일정 동기화를 제공하지 않아요.

Planit과 파일을 교환하려면

Planit에서도 ICS 내보내기 또는 가져오기를 공식 지원하는지 먼저 확인해 주세요.
지원이 확인된 방향의 파일 교환만 가능해요.
먼작귀의 ICS 기능만으로 Planit과 호환된다고 보장하지 않아요.
공식 지원 문의 시 API 문서/허용 인증, ICS 입출력, 구독 URL,
반복/예외/시간대·UID 보존 여부를 확인하면 좋아요.

공식 자료 위치 (선택/복사 가능)

App Store:
https://apps.apple.com/kr/app/id1603481820
Google Play:
https://play.google.com/store/apps/details?id=com.PODO.TODODAY
스토어에 등록된 개발자 웹사이트:
https://www.planit.day/

이 안내를 열어도 사이트 접속·계정 로그인·파일 전송은 하지 않아요.
"""


class CalendarIntegrationDialog(QDialog):
    """Accept means opening the existing file tool, never connecting an account."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("먼작귀 · 캘린더 연동 안내")
        self.resize(620, 560)
        body = QVBoxLayout(self)
        body.addWidget(label("캘린더 연동 안내", "heading"))
        self.status = label(CALENDAR_STATUS_TEXT)
        self.status.setAccessibleName("캘린더 사용 및 연동 지원 상태")
        body.addWidget(self.status)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(INTEGRATION_NOTES)
        self.details.setAccessibleName("캘린더 연동 지원 범위와 Planit 공식 자료 안내")
        self.details.setMinimumHeight(100)
        body.addWidget(self.details, 1)
        controls = QHBoxLayout()
        self.transfer_button = button("ICS 파일 교환 열기", self.accept, True)
        self.close_button = button("닫기", self.reject)
        for control in (self.transfer_button, self.close_button):
            control.setAutoDefault(False)
            controls.addWidget(control)
        body.addLayout(controls)
        self.details.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        fit_window(self)
