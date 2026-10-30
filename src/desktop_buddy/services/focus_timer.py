import logging
import math
from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from desktop_buddy.database.focus_repository import FocusRepository
from desktop_buddy.database.store import Store
from desktop_buddy.models.focus import Clock, Phase, PhaseFinished, SystemClock, TimerSnapshot
from desktop_buddy.models.planning import Occurrence
from desktop_buddy.services.planning_service import PlanningService
from desktop_buddy.services.settings_service import SettingsService


class FocusTimerService(QObject):
    updated = Signal(object)
    records_changed = Signal()
    phase_finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        store: Store,
        settings: SettingsService,
        planning: PlanningService,
        clock: Clock | None = None,
    ) -> None:
        super().__init__()
        self.store, self.settings, self.planning = store, settings, planning
        self.repository = FocusRepository(store.connection)
        self.clock = clock or SystemClock()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self._segment = None
        self._last_mono, self._last_wall = self.clock.monotonic(), self.clock.now()
        self._checkpoint_mono = self._last_mono
        self.status, self.phase, self.next_phase = "idle", "focus", None
        self.session_id = None
        self.recorded = True
        self.elapsed, self.paused = 0.0, 0.0
        self.completed_rounds = 0
        self.reason = ""
        self.task_title, self.category_name = "", "분류 없음"
        self._link = {"task_id": None, "task_key": None, "category_id": None}
        self.plan = self._default_plan()
        self.planned = self.plan["focus"]
        self._restore()
        self._count_day = self.clock.now().astimezone(self.planning.zone).date()

    def _default_plan(self) -> dict:
        settings = self.settings.current
        return {
            "focus": settings.focus_minutes * 60,
            "short_break": settings.break_minutes * 60,
            "long_break": settings.long_break_minutes * 60,
            "interval": settings.long_break_interval,
            "auto": settings.auto_next_phase,
        }

    @property
    def snapshot(self) -> TimerSnapshot:
        return TimerSnapshot(
            self.status,
            self.phase,
            self.planned,
            self.elapsed,
            self.paused,
            self.session_id,
            self.completed_rounds,
            self.next_phase,
            self.task_title,
            self.category_name,
            self.reason,
        )

    def _state(self) -> dict:
        return {
            "status": self.status,
            "phase": self.phase,
            "session_id": self.session_id,
            "next_phase": self.next_phase,
            "completed_rounds": self.completed_rounds,
            "plan": self.plan,
            "link": self._link,
            "reason": self.reason,
        }

    def _restore(self) -> None:
        state = self.repository.load_state()
        self.completed_rounds = (
            max(0, state.get("completed_rounds", 0))
            if type(state.get("completed_rounds", 0)) is int
            else 0
        )
        plan = state.get("plan", {})
        if isinstance(plan, dict) and all(
            type(plan.get(k)) in (int, float) and 1 <= plan[k] <= 86400
            for k in ("focus", "short_break", "long_break")
        ):
            self.plan.update({k: plan[k] for k in ("focus", "short_break", "long_break")})
            self.plan["interval"] = (
                max(1, min(12, plan.get("interval", 4)))
                if type(plan.get("interval", 4)) is int
                else 4
            )
            self.plan["auto"] = plan.get("auto") is True
        if isinstance(state.get("link"), dict):
            self._link.update({key: state["link"].get(key) for key in self._link})
            for key in ("task_id", "category_id"):
                if type(self._link[key]) is not int:
                    self._link[key] = None
            if not isinstance(self._link["task_key"], str):
                self._link["task_key"] = None
        # Unfinished sessions without a valid checkpoint are conservatively interrupted.
        open_rows = self.repository.open_sessions()
        active = next((row for row in open_rows if row["id"] == state.get("session_id")), None)
        with self.store.connection:
            for row in open_rows:
                if row is not active:
                    if row["recorded"]:
                        self.repository.finish(
                            row["id"], self.clock.now(), False, "orphaned_recovery"
                        )
                    else:
                        self.repository.delete(row["id"])
            if active:
                self.session_id = active["id"]
                self.recorded = bool(active["recorded"])
                self.phase = active["kind"]
                self.planned = active["planned_seconds"]
                self.elapsed, self.paused = active["active_seconds"], active["paused_seconds"]
                self.task_title, self.category_name = active["task_title"], active["category_name"]
                self.status, self.reason = "paused", "recovered"
            elif state.get("status") == "ready" and state.get("next_phase") in (
                "focus",
                "short_break",
                "long_break",
            ):
                self.status, self.next_phase = "ready", state["next_phase"]
                self.phase = (
                    state.get("phase")
                    if state.get("phase") in ("focus", "short_break", "long_break")
                    else "focus"
                )
                self.planned = self.plan[self.phase]
                self.elapsed = self.planned
                self.reason = "next_ready"
            self.repository.save_state(self._state())

    def completed_today(self) -> int:
        day = self.clock.now().astimezone(self.planning.zone).date()
        start = datetime.combine(day, time(), self.planning.zone)
        end = datetime.combine(day + timedelta(days=1), time(), self.planning.zone)
        return self.repository.completed_count(start, end)

    def start_clock(self) -> None:
        self.timer.start()

    def _category(self, category_id: int | None) -> tuple[int | None, str, str]:
        category = next(
            (value for value in self.planning.categories() if value.id == category_id), None
        )
        return (
            (category.id, category.name, category.color)
            if category
            else (None, "분류 없음", "#607d8b")
        )

    def start(
        self,
        kind: Phase = "focus",
        minutes: float | None = None,
        task: Occurrence | None = None,
        category_id: int | None = None,
    ) -> None:
        if self.status in ("running", "paused"):
            raise ValueError("진행 중인 타이머를 먼저 중지해 주세요.")
        if kind not in ("focus", "short_break", "long_break"):
            raise ValueError("집중 또는 휴식 시간을 선택해 주세요.")
        seconds = float(minutes) * 60 if minutes is not None else self._default_plan()[kind]
        if not math.isfinite(seconds) or not 1 <= seconds <= 86400:
            raise ValueError("타이머 시간은 1초~24시간 사이여야 해요.")
        self.plan = self._default_plan()
        self.plan[kind] = seconds
        task_id, task_key, task_title = None, None, ""
        if task is not None:
            if task.kind != "task":
                raise ValueError("연결할 할 일을 다시 선택해 주세요.")
            record = self.planning.repository.get("task", task.item_id)
            task_id, task_key, task_title = record.id, task.key, task.title
            if category_id is None:
                category_id = record.category_id
        self._link = {"task_id": task_id, "task_key": task_key, "category_id": category_id}
        self._begin(kind, seconds, task_title)

    def _begin(self, kind: Phase, seconds: float, task_title: str | None = None) -> None:
        category = self._category(self._link["category_id"])
        task_id, task_key = self._link["task_id"], self._link["task_key"]
        title = self.task_title if task_title is None else task_title
        if task_id is not None:
            try:
                record = self.planning.repository.get("task", task_id)
                title = title or record.title
            except LookupError:
                task_id, task_key, title = None, None, ""
                self._link["task_id"], self._link["task_key"] = None, None
        now, mono = self.clock.now(), self.clock.monotonic()
        old = (
            self.status,
            self.phase,
            self.planned,
            self.elapsed,
            self.paused,
            self.session_id,
            self.next_phase,
            self.reason,
            self.task_title,
            self.category_name,
            self.recorded,
        )
        try:
            with self.store.connection:
                recorded = self.settings.current.record_focus if kind == "focus" else True
                item_id = self.repository.create(
                    kind,
                    seconds,
                    now,
                    category,
                    task_id if kind == "focus" and recorded else None,
                    task_key if kind == "focus" and recorded else None,
                    title if kind == "focus" and recorded else "",
                    recorded=recorded,
                )
                self.recorded = recorded
                self.status, self.phase, self.planned, self.session_id = (
                    "running",
                    kind,
                    seconds,
                    item_id,
                )
                self.elapsed, self.paused = 0.0, 0.0
                self.next_phase, self.reason = None, ""
                self.task_title, self.category_name = title, category[1]
                self.repository.save_state(self._state())
        except Exception:
            (
                self.status,
                self.phase,
                self.planned,
                self.elapsed,
                self.paused,
                self.session_id,
                self.next_phase,
                self.reason,
                self.task_title,
                self.category_name,
                self.recorded,
            ) = old
            raise
        self._segment = None
        self._last_wall, self._last_mono, self._checkpoint_mono = now, mono, mono
        self.updated.emit(self.snapshot)
        self.records_changed.emit()

    def start_next(self) -> None:
        if self.status != "ready" or self.next_phase is None:
            raise ValueError("다음 단계를 기다리는 상태가 아니에요.")
        self._begin(self.next_phase, self.plan[self.next_phase])

    def skip_break(self) -> None:
        if self.status != "ready" or self.next_phase == "focus":
            raise ValueError("휴식을 기다리는 상태가 아니에요.")
        self._begin("focus", self.plan["focus"])

    def set_auto_next(self, enabled: bool) -> None:
        self.plan["auto"] = bool(enabled)
        self._persist()

    def _observe(self) -> None:
        now, mono = self.clock.now(), self.clock.monotonic()
        delta = mono - self._last_mono
        wall_delta = (now - self._last_wall).total_seconds()
        if self.status == "running":
            if (
                not math.isfinite(delta)
                or delta < 0
                or delta > 5
                or wall_delta <= 0
                or abs(wall_delta - delta) > 2
            ):
                if delta == 0 and wall_delta == 0:
                    return
                self.status = "paused"
                self.reason = (
                    "clock_changed"
                    if delta < 0 or wall_delta <= 0 or abs(wall_delta - delta) > 2
                    else "long_gap"
                )
                self._persist()
                self._segment = None
            elif delta > 0:
                credit = min(delta, max(0, self.planned - self.elapsed))
                end = self._last_wall + timedelta(seconds=wall_delta * credit / delta)
                if self._segment is None:
                    self._segment = {
                        "id": None,
                        "start": self._last_wall,
                        "end": end,
                        "seconds": credit,
                    }
                else:
                    self._segment["end"] = end
                    self._segment["seconds"] += credit
                self.elapsed += credit
        elif self.status == "paused" and math.isfinite(delta) and delta > 0:
            self.paused += delta
        self._last_mono, self._last_wall = mono, now

    def _persist(self) -> None:
        segment_id = None
        with self.store.connection:
            if self.session_id is not None:
                self.repository.progress(self.session_id, self.elapsed, self.paused)
                if (
                    self.phase == "focus"
                    and self.recorded
                    and self._segment
                    and self._segment["seconds"] > 0
                ):
                    value = self._segment
                    segment_id = self.repository.segment(
                        value["id"], self.session_id, value["start"], value["end"], value["seconds"]
                    )
            self.repository.save_state(self._state())
        if segment_id is not None:
            self._segment["id"] = segment_id
        self._checkpoint_mono = self.clock.monotonic()

    def _storage_error(self, error: Exception) -> None:
        logging.getLogger(__name__).warning("Timer checkpoint failed (%s)", type(error).__name__)
        changed = self.reason != "storage_error"
        self.status = (
            "paused" if self.session_id is not None else ("ready" if self.next_phase else "idle")
        )
        self.reason = "storage_error"
        self._last_wall, self._last_mono = self.clock.now(), self.clock.monotonic()
        if changed:
            self.error.emit(
                "기록을 저장하지 못해 타이머를 일시정지했어요. 저장 공간을 확인하고 재개해 주세요."
            )

    def tick(self) -> None:
        day = self.clock.now().astimezone(self.planning.zone).date()
        if day != self._count_day:
            self._count_day = day
            self.records_changed.emit()
        if self.status not in ("running", "paused"):
            return
        try:
            self._observe()
            if self.status == "running" and self.elapsed >= self.planned - 1e-7:
                self._finish(True, "completed")
                return
            if self.clock.monotonic() - self._checkpoint_mono >= 5:
                self._persist()
                self.records_changed.emit()
        except Exception as error:
            self._storage_error(error)
        self.updated.emit(self.snapshot)

    def pause(self, reason: str = "manual") -> None:
        if self.status != "running":
            return
        self._observe()
        if self.elapsed >= self.planned - 1e-7:
            self._finish(True, "completed", auto_advance=False)
            return
        self.status, self.reason = "paused", reason
        self._persist()
        self._segment = None
        self.updated.emit(self.snapshot)
        self.records_changed.emit()

    def resume(self) -> None:
        if self.status != "paused":
            return
        self._observe()
        self._persist()
        self.status, self.reason = "running", ""
        self._segment = None
        self._last_wall, self._last_mono = self.clock.now(), self.clock.monotonic()
        self._persist()
        self.updated.emit(self.snapshot)

    def _finish(self, completed: bool, reason: str, auto_advance: bool = True) -> None:
        item_id, kind, elapsed = self.session_id, self.phase, self.elapsed
        rounds = self.completed_rounds + (1 if completed and kind == "focus" else 0)
        next_kind = (
            ("long_break" if rounds % self.plan["interval"] == 0 else "short_break")
            if kind == "focus"
            else "focus"
        )
        old = (self.status, self.completed_rounds, self.next_phase, self.reason, self.session_id)
        try:
            with self.store.connection:
                self._persist()
                if self.recorded:
                    self.repository.finish(item_id, self.clock.now(), completed, reason)
                else:
                    self.repository.delete(item_id)
                self.completed_rounds = rounds
                self.status = "ready" if completed else "idle"
                self.next_phase = next_kind if completed else None
                self.reason = "next_ready" if completed else reason
                self.session_id = None
                self.repository.save_state(self._state())
        except Exception:
            self.status, self.completed_rounds, self.next_phase, self.reason, self.session_id = old
            raise
        self._segment = None
        if not completed:
            self.elapsed, self.paused = 0.0, 0.0
        self.records_changed.emit()
        self.updated.emit(self.snapshot)
        if completed:
            self.phase_finished.emit(PhaseFinished(kind, item_id, elapsed, next_kind))
            if self.plan["auto"] and auto_advance:
                self.start_next()

    def stop(self) -> None:
        if self.status in ("running", "paused"):
            self._observe()
            completed = self.elapsed >= self.planned - 1e-7 and self.status == "running"
            self._finish(completed, "completed" if completed else "stopped", auto_advance=False)
        elif self.status == "ready":
            self.status, self.next_phase, self.reason = "idle", None, ""
            self._persist()
            self.updated.emit(self.snapshot)

    def reset(self) -> None:
        self.stop()
        self.completed_rounds = 0
        self.status, self.phase, self.next_phase, self.reason = "idle", "focus", None, ""
        self.plan = self._default_plan()
        self.planned, self.elapsed, self.paused = self.plan["focus"], 0.0, 0.0
        self._persist()
        self.updated.emit(self.snapshot)

    def shutdown(self) -> None:
        self.timer.stop()
        if self.status == "running":
            self.pause("app_closed")
        elif self.status == "paused":
            self._observe()
            self._persist()
