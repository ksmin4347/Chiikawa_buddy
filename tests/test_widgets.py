from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from desktop_buddy.characters.animation import AnimationState, load_clips
from desktop_buddy.core.paths import asset_directory
from desktop_buddy.core.settings import Settings
from desktop_buddy.ui.pet import PetWindow


@pytest.fixture
def pet(qapp):
    widget = PetWindow(
        AnimationState(load_clips(asset_directory() / "default_character")), Settings()
    )
    widget.move(100, 100)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.hide()
    widget.bubble.close()
    widget.deleteLater()
    qapp.processEvents()


def test_single_click_is_delayed_and_double_click_cancels_it(pet):
    clicks = QSignalSpy(pet.single_clicked)
    opens = QSignalSpy(pet.manage_requested)
    center = QPoint(pet.width() // 2, pet.height() // 2)
    QTest.mouseClick(pet, Qt.MouseButton.LeftButton, pos=center)
    assert clicks.count() == 0
    QTest.mouseDClick(pet, Qt.MouseButton.LeftButton, pos=center)
    QTest.qWait(QApplication.doubleClickInterval() + 80)
    assert opens.count() == 1
    assert clicks.count() == 0


def test_single_click_reacts_once(pet):
    clicks = QSignalSpy(pet.single_clicked)
    QTest.mouseClick(pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    QTest.qWait(QApplication.doubleClickInterval() + 80)
    assert clicks.count() == 1


def test_drag_saves_position_without_click(pet):
    clicks = QSignalSpy(pet.single_clicked)
    moved = QSignalSpy(pet.position_changed)
    center = QPoint(80, 90)
    QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=center)
    target = center + QPoint(80, 40)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(target),
        QPointF(pet.mapToGlobal(target)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(pet, event)
    QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=center)
    QTest.qWait(QApplication.doubleClickInterval() + 60)
    assert moved.count() == 1
    assert clicks.count() == 0
    assert pet.pos() == QPoint(180, 140)


def test_hidden_animation_stops_and_reduce_motion(pet):
    assert pet.animation_timer.isActive()
    pet.hide()
    assert not pet.animation_timer.isActive()
    pet.show()
    assert pet.animation_timer.isActive()
    pet.apply_settings(replace(Settings(), reduce_motion=True))
    pet.react()
    assert not pet.animation_timer.isActive()
    assert pet.animation.state == "idle"


def test_mask_excludes_empty_corners(pet):
    assert pet.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not pet.mask().isEmpty()
    assert not pet.mask().contains(QPoint(0, 0))
    assert pet.mask().contains(QPoint(88, 100))
