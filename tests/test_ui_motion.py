import os
import time

import pytest

pytest.importorskip('PyQt5')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication, QProgressBar, QWidget  # noqa: E402

from app import power  # noqa: E402
from app.ui import motion  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def _spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec_()


def test_fade_in_removes_effect_and_respects_switch(qapp):
    w = QWidget()
    child = QWidget(w)
    w.show()
    motion.set_enabled(True)
    motion.fade_in(child, 60)
    assert child.graphicsEffect() is not None
    _spin(250)
    assert child.graphicsEffect() is None                 # после анимации никакой нагрузки
    motion.set_enabled(False)
    motion.fade_in(child, 60)
    assert child.graphicsEffect() is None                 # выключено — анимации нет вообще
    motion.set_enabled(True)
    w.hide()
    motion.fade_in(child, 60)
    assert child.graphicsEffect() is None                 # окно скрыто — не анимируем


def test_progress_bar_animates_to_value(qapp):
    w = QWidget()
    bar = QProgressBar(w)
    bar.setRange(0, 100)
    w.show()
    motion.set_enabled(True)
    motion.animate_bar(bar, 80, 60)
    _spin(200)
    assert bar.value() == 80


def test_power_helpers_are_safe_everywhere():
    power.lower_priority()
    power.enter_background()
    power.leave_background()


def test_process_name_cache_is_fast_and_consistent(env):
    from app.process_monitor import ProcessMonitor
    store = env[0]
    mon = ProcessMonitor(store)
    first = mon._current_process_names()
    assert first and mon._name_cache
    t = time.perf_counter()
    for _ in range(20):
        again = mon._current_process_names()
    per_poll_ms = (time.perf_counter() - t) / 20 * 1000
    assert again >= {n for n in first if n in again} and per_poll_ms < 50
