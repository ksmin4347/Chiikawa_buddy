import pytest

from desktop_buddy.core.geometry import Rect, keep_visible


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((100, 100), (100, 100)),
        ((900, 900), (624, 424)),
        ((-200, -100), (0, 0)),
    ],
)
def test_screen_bounds(point, expected):
    assert keep_visible(*point, 176, [Rect(0, 0, 800, 600)]) == expected


def test_negative_coordinate_monitor():
    assert keep_visible(-900, 100, 176, [Rect(-1280, 0, 1280, 1000), Rect(0, 0, 1920, 1040)]) == (
        -900,
        100,
    )


def test_monitor_removed_and_gap():
    assert keep_visible(-1500, 100, 176, [Rect(0, 0, 1920, 1040)]) == (0, 100)
    assert keep_visible(850, 50, 176, [Rect(0, 0, 800, 600), Rect(1200, 0, 800, 600)]) == (624, 50)


def test_small_and_no_screens():
    assert keep_visible(500, 500, 176, [Rect(0, 0, 80, 80)]) == (0, 0)
    assert keep_visible(-100, 200, 176, []) == (-100, 200)
