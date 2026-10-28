import logging
from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog

from desktop_buddy.models.planning import CalendarEvent, Task
from desktop_buddy.ui.planning_dialogs import (
    CategoryDialog,
    ItemEditor,
    ScopeDialog,
    confirm_delete,
)


class PlanningActions(QObject):
    def __init__(self, service, owner):
        super().__init__(owner)
        self.service, self.owner = service, owner

    def _editor(self, record, commit, single=False, focus_date=False):
        dialog = ItemEditor(self.service, record, commit, self.owner, single=single)
        if focus_date and isinstance(record, Task):
            dialog.date_edit.setFocus()
        try:
            return dialog.exec()
        finally:
            dialog.deleteLater()

    def add_task(self, day=None):
        record = Task("", day or self.service.today())
        self._editor(record, self.service.save)

    def add_event(self, day=None):
        start = datetime.combine(day or self.service.today(), time(14), self.service.zone)
        self._editor(CalendarEvent("", start, start + timedelta(hours=1)), self.service.save)

    def _scope(self, occurrence, deleting=False):
        if not occurrence.repeated:
            if deleting and not confirm_delete(self.owner, f"「{occurrence.title}」를 삭제할까요?"):
                return None
            return "all"
        dialog = ScopeDialog(occurrence, deleting, self.owner)
        try:
            return dialog.scope if dialog.exec() == QDialog.DialogCode.Accepted else None
        finally:
            dialog.deleteLater()

    def edit(self, occurrence, focus_date=False):
        if occurrence is None:
            return
        scope = self._scope(occurrence)
        if scope is not None:
            try:
                record = self.service.draft(occurrence, scope)
                self._editor(
                    record,
                    lambda value: self.service.edit(occurrence, value, scope),
                    single=scope == "one",
                    focus_date=focus_date,
                )
            except Exception as error:
                self._error(error)

    def delete(self, occurrence):
        if occurrence is None:
            return
        scope = self._scope(occurrence, True)
        if scope is not None:
            try:
                self.service.delete(occurrence, scope)
            except Exception as error:
                self._error(error)

    def manage_categories(self):
        dialog = CategoryDialog(self.service, self.owner)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _error(self, error):
        logging.getLogger(__name__).warning("Planning action failed (%s)", type(error).__name__)
        text = (
            str(error)
            if isinstance(error, (ValueError, LookupError))
            else "저장하지 못했어요. 저장 공간을 확인해 주세요."
        )
        self.owner.statusBar().showMessage(text, 15000)
