from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from desktop_buddy.database.companion_repository import CompanionRepository
from desktop_buddy.models.companion import Briefing
from desktop_buddy.services.companion_service import CompanionService


class BriefingService(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, planning, settings, companion: CompanionService) -> None:
        super().__init__()
        self.planning, self.settings, self.companion = planning, settings, companion
        self.repository: CompanionRepository = companion.repository
        self.startup = True
        self.startup_day = companion.clock.now().astimezone(planning.zone).date()
        self.can_notify = lambda: False
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.poll)
        settings.changed.connect(self.poll)

    def start(self) -> None:
        self.timer.start()
        self.poll()

    def stop(self) -> None:
        self.timer.stop()

    def build(self) -> Briefing:
        now = self.companion.clock.now().astimezone(self.planning.zone)
        day = now.date()
        items = self.planning.occurrences(day, day + timedelta(days=1))
        tasks = [item for item in items if item.kind == "task" and not item.completed]
        events = [item for item in items if item.kind == "event"]
        upcoming = next((item for item in events if not item.all_day and item.start >= now), None)
        overdue = self.planning.overdue_tasks(day)
        deadlines = sorted(
            (
                item
                for item in [*tasks, *overdue]
                if item.record.due_at is not None
                and item.record.due_at.astimezone(self.planning.zone).date() == day
            ),
            key=lambda item: item.record.due_at,
        )
        study = [
            item
            for item in items
            if item.category
            and item.category.name == "공부"
            and (item.kind == "event" or not item.completed)
        ]
        summary = f"오늘 일정 {len(events)}개 · 남은 할 일 {len(tasks)}개"
        if upcoming:
            summary += f"\n가까운 일정 · {upcoming.start:%H:%M} {upcoming.title}"
        else:
            summary += "\n오늘 남은 시간 지정 일정이 없어요."
        details = []
        if tasks:
            details.append("할 일 · " + ", ".join(item.title for item in tasks[:5]))
        if deadlines:
            details.append(
                "오늘 마감 · "
                + ", ".join(
                    f"{item.record.due_at.astimezone(self.planning.zone):%H:%M} {item.title}"
                    for item in deadlines[:3]
                )
            )
        if study:
            details.append("공부 분류 계획 · " + ", ".join(item.title for item in study[:3]))
        details.append(f"이전 미완료 · {len(overdue)}개 (자동으로 없애지 않아요)")
        heading = f"{day.month}월 {day.day}일 {'월화수목금토일'[day.weekday()]}요일"
        return Briefing(day, heading, summary, "\n".join(details))

    def manual(self) -> Briefing:
        briefing = self.build()
        with self.repository.connection:
            self.repository.claim_message("briefing", briefing.day)
        return briefing

    def poll(self, *_args) -> None:
        try:
            self.companion.guard.observe()
            current = self.settings.current
            now = self.companion.clock.now().astimezone(self.planning.zone)
            if not current.briefing_enabled or self.companion.guard.warning:
                return
            last = self.repository.last_message("briefing")
            if last is not None and now.date() <= last:
                return
            scheduled = datetime.combine(
                now.date(), time.fromisoformat(current.briefing_time), self.planning.zone
            )
            if (
                not (self.startup and now.date() == self.startup_day and current.briefing_on_start)
                and now < scheduled
            ):
                return
            if self.companion.quiet() or not self.can_notify():
                return
            briefing = self.build()
            with self.repository.connection:
                claimed = self.repository.claim_message("briefing", now.date())
            self.startup = False
            if claimed:
                self.ready.emit(briefing)
        except Exception:
            self.failed.emit("브리핑을 준비하지 못했어요. 저장 공간과 날짜를 확인해 주세요.")
