import json
import math
import collections
import re
import subprocess
import sys
import threading
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

def _bootstrap_pyside6_dlls():
    exe_dir = Path(sys.executable).resolve().parent
    if getattr(sys, 'frozen', False):
        frozen_base = Path(getattr(sys, '_MEIPASS', exe_dir / '_internal'))
        dll_dirs = [
            frozen_base,
            frozen_base / 'PySide6',
            frozen_base / 'shiboken6',
        ]
        preload = [
            frozen_base / 'python312.dll',
            frozen_base / 'python3.dll',
            frozen_base / 'Qt6Core.dll',
            frozen_base / 'Qt6Gui.dll',
            frozen_base / 'Qt6Widgets.dll',
        ]
        preload.extend(sorted((frozen_base / 'shiboken6').glob('shiboken6*.dll')))
        preload.extend(sorted((frozen_base).glob('shiboken6*.dll')))
        preload.extend(sorted((frozen_base / 'PySide6').glob('pyside6*.dll')))
        preload.extend(sorted((frozen_base).glob('pyside6*.dll')))
    else:
        dll_dirs = [
            exe_dir,
            exe_dir / 'Library' / 'bin',
            exe_dir / 'Lib' / 'site-packages' / 'shiboken6',
            exe_dir / 'Lib' / 'site-packages' / 'PySide6',
        ]
        preload = [
            exe_dir / 'python3.dll',
            exe_dir / 'Library' / 'bin' / 'Qt6Core.dll',
            exe_dir / 'Library' / 'bin' / 'Qt6Gui.dll',
            exe_dir / 'Library' / 'bin' / 'Qt6Widgets.dll',
            exe_dir / 'Lib' / 'site-packages' / 'shiboken6' / 'shiboken6.abi3.dll',
            exe_dir / 'Lib' / 'site-packages' / 'PySide6' / 'pyside6.abi3.dll',
        ]
    for dll_dir in dll_dirs:
        if dll_dir.exists():
            try:
                os.add_dll_directory(str(dll_dir))
            except Exception:
                pass
    for dll_path in preload:
        if dll_path.exists():
            try:
                ctypes.WinDLL(str(dll_path))
            except Exception:
                pass


import os

_bootstrap_pyside6_dlls()

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal, QAbstractNativeEventFilter, QEvent
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QRadialGradient, QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import tracker


class Bridge(QObject):
    log = Signal(str)
    status = Signal(str, str)
    stats = Signal()
    error = Signal(str, str)
    orbFlash = Signal()
    orbHit = Signal(str)


class OrbWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = '0'
        self.setMinimumSize(210, 210)

    def set_value(self, value: str):
        self.value = value
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(14, 14, -14, -14)
        grad = QRadialGradient(rect.center() + QPoint(-18, -22), rect.width() * 0.62)
        grad.setColorAt(0.0, QColor('#F1FDFF'))
        grad.setColorAt(0.24, QColor('#A8E0FF'))
        grad.setColorAt(0.56, QColor('#5DA5F7'))
        grad.setColorAt(1.0, QColor('#305ADE'))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor(233, 248, 255, 230), 2))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor(230, 212, 255, 180), 3))
        painter.drawArc(rect.adjusted(-16, 30, 16, -30), 0, 360 * 16)
        painter.setPen(QPen(QColor(196, 238, 255, 180), 2))
        painter.drawArc(rect.adjusted(18, -14, 20, -42), 22 * 16, 144 * 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 90))
        painter.drawEllipse(QRect(rect.left() + 24, rect.top() + 18, 68, 40))
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.drawEllipse(QRect(rect.left() + 42, rect.top() + 30, 32, 16))
        painter.setPen(QColor('#F7FDFF'))
        painter.setFont(QFont('Microsoft YaHei', 12, QFont.Weight.Bold))
        painter.drawText(rect.adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignHCenter, '污染')
        painter.setFont(QFont('Segoe UI Light', 40, QFont.Weight.Bold))
        painter.drawText(rect.adjusted(0, 72, 0, 0), Qt.AlignmentFlag.AlignHCenter, self.value)


class CaptureOverlay(QWidget):
    captured = Signal(QRect)
    cancelled = Signal()

    def __init__(self, pixmap: QPixmap):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.origin = QPoint()
        self.band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.background = pixmap

    def paintEvent(self, _event):
        painter = QPainter(self)
        if not self.background.isNull():
            painter.drawPixmap(self.rect(), self.background)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

    def mousePressEvent(self, event):
        self.origin = event.globalPosition().toPoint()
        self.band.setGeometry(QRect(event.position().toPoint(), event.position().toPoint()))
        self.band.show()

    def mouseMoveEvent(self, event):
        self.band.setGeometry(QRect(self.origin - self.pos(), event.globalPosition().toPoint() - self.pos()).normalized())

    def mouseReleaseEvent(self, event):
        rect = QRect(self.origin, event.globalPosition().toPoint()).normalized()
        self.band.hide()
        self.captured.emit(rect)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()


class FloatingOrbWindow(QWidget):
    singleClicked = Signal()
    doubleClicked = Signal()
    captureRequested = Signal()
    openDirRequested = Signal()
    showMainRequested = Signal()
    topmostToggled = Signal(bool)
    quitRequested = Signal()
    positionChanged = Signal(int, int, str)

    def __init__(self):
        super().__init__(None)
        self.collapsed_width = 88
        self.expanded_width = 348
        self.window_height = 102
        self.orb_size = 74
        self.orb_offset = 8
        self.peek_width = 68
        self.tail_visible = False
        self.drag_offset = None
        self.status_text = '待机'
        self.status_color = QColor('#8C98A7')
        self.value = '0'
        self.latest_name = '-'
        self.session_hits = 0
        self.running = False
        self.topmost_enabled = True
        self.dock_side = 'right'
        self.opacity_level = 0.94
        self._press_window_pos = None
        self._dragging = False
        self._pulse_phase = 0.0
        self._flash_strength = 0.0
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.singleClicked.emit)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)
        self._tail_hide_timer = QTimer(self)
        self._tail_hide_timer.setSingleShot(True)
        self._tail_hide_timer.timeout.connect(lambda: self._set_tail_visible(False))
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._hide_hit_badge)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._advance_animation)
        self._anim_timer.start(50)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setWindowOpacity(self.opacity_level)
        self.resize(self.collapsed_width, self.window_height)

        self.tail = QFrame(self)
        self.tail.setObjectName('OrbTail')
        self.tail.setGeometry(84, 4, self.expanded_width - 92, 94)
        self.tail.hide()

        self.latest_label = QLabel('-', self.tail)
        self.latest_label.setObjectName('OrbLatest')
        self.latest_label.setGeometry(22, 14, 170, 24)

        self.status_label = QLabel('待机', self.tail)
        self.status_label.setObjectName('OrbStatus')
        self.status_label.setGeometry(22, 38, 126, 22)

        self.stats_label = QLabel('总污染 0  ·  本次 0', self.tail)
        self.stats_label.setObjectName('OrbStats')
        self.stats_label.setGeometry(22, 60, 150, 18)

        self.hint_label = QLabel('单击展开主面板', self.tail)
        self.hint_label.setObjectName('OrbHint')
        self.hint_label.setGeometry(154, 38, 98, 16)

        self.hint_label2 = QLabel('双击开始/停止  ·  右键更多操作', self.tail)
        self.hint_label2.setObjectName('OrbHint')
        self.hint_label2.setGeometry(116, 58, 138, 16)

        self.hit_badge = QLabel('', self.tail)
        self.hit_badge.setObjectName('OrbBadge')
        self.hit_badge.setGeometry(138, 14, 108, 22)
        self.hit_badge.hide()

        self._menu = QMenu(self)
        style = QApplication.style()
        self._act_start = self._menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), '开始识别')
        self._act_stop = self._menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop), '停止识别')
        self._menu.addSeparator()
        self._act_capture = self._menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), '模板截图')
        self._act_dir = self._menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), '打开目录')
        self._menu.addSeparator()
        self._act_show = self._menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DesktopIcon), '显示主面板')
        self._act_topmost = self._menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarShadeButton), '取消置顶')
        self._menu.addSeparator()
        self._act_quit = self._menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton), '退出')

        self._act_capture.triggered.connect(self.captureRequested.emit)
        self._act_dir.triggered.connect(self.openDirRequested.emit)
        self._act_show.triggered.connect(self.showMainRequested.emit)
        self._act_topmost.triggered.connect(self._toggle_topmost_from_menu)
        self._act_quit.triggered.connect(self.quitRequested.emit)

        self.setStyleSheet("""
        QFrame#OrbTail {
            background: rgba(228,238,255,0.18);
            border: 1px solid rgba(255,255,255,0.34);
            border-radius: 24px;
        }
        QLabel#OrbLatest { color: rgba(15,31,52,0.96); font: 700 16px 'Microsoft YaHei'; }
        QLabel#OrbStatus { color: rgba(22,74,108,0.96); font: 600 13px 'Microsoft YaHei'; }
        QLabel#OrbStats { color: rgba(20,40,63,0.92); font: 500 12px 'Microsoft YaHei'; }
        QLabel#OrbHint { color: rgba(36,58,84,0.72); font: 500 10px 'Microsoft YaHei'; }
        QLabel#OrbBadge {
            background: rgba(196,162,255,0.20);
            border: 1px solid rgba(206,177,255,0.48);
            border-radius: 11px;
            color: rgba(68,34,96,0.96);
            font: 700 10px 'Microsoft YaHei';
            padding-left: 8px;
        }
        """)

    def set_data(self, total: str, latest: str, species_count: int, session_hits: int | None = None):
        self.value = total
        self.latest_name = latest or '-'
        if session_hits is not None:
            self.session_hits = session_hits
        self.latest_label.setText(self.latest_name)
        self.stats_label.setText(f'总污染 {total}  ·  本次 {self.session_hits}')
        self.update()

    def set_status(self, text: str, color: str, battle_locked: bool = False):
        self.status_text = text
        self.status_color = QColor(color)
        self.running = text != '待机'
        self.status_label.setText(f'{text}{" · 已锁定" if battle_locked and self.running else ""}')
        self.update()

    def set_topmost_enabled(self, enabled: bool):
        self.topmost_enabled = bool(enabled)
        self._act_topmost.setText('取消置顶' if self.topmost_enabled else '开启置顶')

    def set_running_actions(self, running: bool):
        self._act_start.setVisible(not running)
        self._act_stop.setVisible(running)

    def bind_start_stop(self, start_slot, stop_slot):
        self._act_start.triggered.connect(start_slot)
        self._act_stop.triggered.connect(stop_slot)

    def set_saved_position(self, x, y, dock_side):
        if dock_side in ('left', 'right'):
            self.dock_side = dock_side
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        if x is None or y is None:
            y = geo.top() + 160
        y = min(max(int(y), geo.top() + 20), geo.bottom() - self.height() - 20)
        if self.dock_side == 'left':
            self.move(geo.left() - (self.collapsed_width - self.peek_width), y)
        else:
            self.move(geo.right() - self.peek_width + 1, y)

    def show_hint(self, text: str, timeout_ms: int = 1600):
        self.hit_badge.setText(text)
        self.hit_badge.adjustSize()
        width = min(max(92, self.hit_badge.width() + 14), 128)
        self.hit_badge.resize(width, 22)
        self.hit_badge.move(126, 14)
        self.hit_badge.show()
        self._hint_timer.start(timeout_ms)

    def notify_hit(self, pet_name: str, session_hits: int):
        self.latest_name = pet_name
        self.session_hits = session_hits
        self.latest_label.setText(pet_name)
        self.stats_label.setText(f'总污染 {self.value}  ·  本次 {self.session_hits}')
        self.flash_hit()
        self.show_hint(f'+1 {pet_name}', 1800)

    def flash_hit(self):
        self._flash_strength = 1.0
        self.update()
        self._flash_timer.start(360)

    def _clear_flash(self):
        self._flash_strength = 0.0
        self.update()

    def _advance_animation(self):
        self._pulse_phase = (self._pulse_phase + 0.18) % (math.tau)
        if self._flash_strength > 0:
            self._flash_strength = max(0.0, self._flash_strength - 0.08)
        self.update()

    def _toggle_topmost_from_menu(self):
        self.topmostToggled.emit(not self.topmost_enabled)

    def _hide_hit_badge(self):
        if hasattr(self, 'hit_badge') and self.hit_badge is not None:
            self.hit_badge.hide()

    def _set_tail_visible(self, visible: bool):
        visible = bool(visible)
        self._tail_hide_timer.stop()
        if self.tail_visible == visible:
            return
        self.tail_visible = visible
        self.tail.setVisible(visible)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        y = min(max(self.y(), geo.top() + 20), geo.bottom() - self.height() - 20)
        if visible:
            self.resize(self.expanded_width, self.window_height)
            x = geo.left() + 18 if self.dock_side == 'left' else geo.right() - self.expanded_width - 18
        else:
            self.resize(self.collapsed_width, self.window_height)
            x = geo.left() - (self.collapsed_width - self.peek_width) if self.dock_side == 'left' else geo.right() - self.peek_width + 1
        self.move(x, y)
        self.update()

    def enterEvent(self, _event):
        self._tail_hide_timer.stop()
        self._set_tail_visible(True)

    def leaveEvent(self, _event):
        if not self._menu.isVisible():
            self._tail_hide_timer.start(320)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_window_pos = self.pos()
            self._dragging = False
        elif event.button() == Qt.MouseButton.RightButton:
            self._tail_hide_timer.stop()
            self._set_tail_visible(True)
            self._menu.exec(event.globalPosition().toPoint())
            self._tail_hide_timer.start(280)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self.drag_offset
            if self._press_window_pos is not None and (target - self._press_window_pos).manhattanLength() > 6:
                self._dragging = True
            self.move(target)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_offset is not None:
            moved = 0
            if self._press_window_pos is not None:
                moved = (self.pos() - self._press_window_pos).manhattanLength()
            self.drag_offset = None
            self._press_window_pos = None
            self._snap_to_edge()
            if not self._dragging and moved < 6:
                self._click_timer.start(220)
            self._dragging = False

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.doubleClicked.emit()

    def _snap_to_edge(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        center_x = self.frameGeometry().center().x()
        self.dock_side = 'right' if center_x >= geo.center().x() else 'left'
        y = min(max(self.y(), geo.top() + 20), geo.bottom() - self.height() - 20)
        x = geo.left() - (self.collapsed_width - self.peek_width) if self.dock_side == 'left' else geo.right() - self.peek_width + 1
        self.move(x, y)
        self.positionChanged.emit(x, y, self.dock_side)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        orb_rect = QRect(self.orb_offset, self.orb_offset + 1, self.orb_size, self.orb_size)
        glow_rect = QRect(0, 0, 90, 90)
        pulse = 0.5 + 0.5 * math.sin(self._pulse_phase)
        glow_alpha = 42 + int(18 * pulse if self.running else 0)
        glow = QRadialGradient(glow_rect.center(), 42)
        glow.setColorAt(0.0, QColor(226, 246, 255, 58))
        glow.setColorAt(0.58, QColor(120, 190, 255, glow_alpha))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(glow_rect)
        if self._flash_strength > 0:
            flash = QRadialGradient(glow_rect.center(), 46)
            flash_alpha = int(110 * self._flash_strength)
            flash.setColorAt(0.0, QColor(210, 176, 255, flash_alpha))
            flash.setColorAt(0.60, QColor(178, 140, 255, int(76 * self._flash_strength)))
            flash.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(flash)
            painter.drawEllipse(glow_rect.adjusted(-2, -2, 2, 2))

        grad = QRadialGradient(orb_rect.center() + QPoint(-10, -10), 44)
        grad.setColorAt(0.0, QColor('#F2FDFF'))
        grad.setColorAt(0.20, QColor('#DDF4FF'))
        grad.setColorAt(0.58, QColor('#5DA5F7'))
        grad.setColorAt(1.0, QColor('#3468E2'))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor(236, 247, 255, 235), 2))
        painter.drawEllipse(orb_rect)
        painter.setPen(QPen(QColor(245, 210, 241, 210), 3))
        painter.drawArc(orb_rect.adjusted(-8, 18, 8, -16), 205 * 16, 136 * 16)
        painter.setPen(QPen(QColor(222, 246, 255, 188), 2))
        painter.drawArc(orb_rect.adjusted(-10, -8, 10, 10), 8 * 16, 144 * 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 110))
        painter.drawEllipse(QRect(24, 22, 30, 14))
        painter.setFont(QFont('Microsoft YaHei', 10, QFont.Weight.Bold))
        text_rect = orb_rect.adjusted(0, 10, 0, 0)
        num_rect = orb_rect.adjusted(0, 27, 0, 0)
        painter.setPen(QColor(255, 255, 255, 105))
        painter.drawText(text_rect.adjusted(1, 1, 1, 1), Qt.AlignmentFlag.AlignHCenter, '污染')
        painter.setPen(QColor('#13253A'))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter, '污染')
        painter.setFont(QFont('Segoe UI', 26, QFont.Weight.DemiBold))
        painter.setPen(QColor(255, 255, 255, 112))
        painter.drawText(num_rect.adjusted(1, 1, 1, 1), Qt.AlignmentFlag.AlignHCenter, self.value)
        painter.setPen(QColor('#0D1F34'))
        painter.drawText(num_rect, Qt.AlignmentFlag.AlignHCenter, self.value)
        painter.setBrush(self.status_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRect(66, 16, 10, 10))

class WinHotkeyFilter(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if sys.platform != 'win32':
            return False, 0
        if event_type not in ('windows_generic_MSG', 'windows_dispatcher_MSG'):
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        except Exception:
            return False, 0
        if msg.message == self.WM_HOTKEY and int(msg.wParam) == 1:
            self.callback()
            return True, 0
        return False, 0

class QtTrackerWindow(QMainWindow):
    UNKNOWN_PET_NAMES = {'未知精灵', 'unknown', 'Unknown', ''}
    NAME_BLACKLIST = {
        '单次扫描',
        '开始截图监听',
        '开始实时识别',
        '截图监听',
        '实时识别',
        '设置',
        '打开报表',
        '重置',
        '停止',
        '日志输出',
        '精灵计数池',
        '名称',
        '计数',
        '污染',
        '实时状态',
    }

    def __init__(self):
        super().__init__()
        tracker.init_files()
        self.cfg = tracker.merge_defaults(tracker.load_json(tracker.CONFIG_PATH, tracker.default_config()), tracker.default_config())
        self.state = tracker.load_json(tracker.STATE_PATH, {'total_pollution': 0, 'processed_hashes': {}, 'records': [], 'pet_pool': {}})
        self.state.setdefault('pet_pool', {})
        self.name_engine = None
        self.species_names = []
        self.species_alias = {}
        self._name_cache_name = None
        self._name_cache_reason = 'name=init'
        self._name_cache_raw = ''
        self._name_cache_ts = 0.0
        self._name_last_ocr_ts = 0.0
        self._tracked_species_name = None
        self._tracked_species_bbox = None
        self._tracked_species_ts = 0.0
        self._last_full_scan_ts = 0.0
        self.species_templates = []
        self.attribute_templates = []
        self.species_attribute_map = {}
        self.running = False
        self.session_hits = 0
        self.battle_locked_state = False
        self.stop_event = threading.Event()
        self.worker = None
        self.drag_pos = None
        self.logs = []
        self.overlay = None
        self.floating_orb = None
        self.tray = None
        self.tray_menu = None
        self.hotkey_filter = None
        self.hotkey_registered = False
        self._quitting = False
        self.bridge = Bridge()
        self.bridge.log.connect(self._append_log)
        self.bridge.status.connect(self._set_status)
        self.bridge.stats.connect(self.refresh_stats)
        self.bridge.error.connect(lambda t, m: QMessageBox.critical(self, t, m))
        self.bridge.orbFlash.connect(self._flash_floating_orb)
        self.bridge.orbHit.connect(self._notify_orb_hit)
        self._load_species_db()
        self._load_species_templates()
        self._load_attribute_templates()

        self.setWindowTitle('洛克污染统计器')
        self.resize(1080, 660)
        self.setMinimumSize(1080, 660)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build_ui()
        self._apply_styles()
        self._set_status('待机', '#8C98A7')
        self.refresh_stats()
        self.clock = QTimer(self)
        self.clock.timeout.connect(self._tick_clock)
        self.clock.start(1000)
        self._tick_clock()
        self._setup_tray()
        self._setup_global_hotkey()
        self._setup_floating_orb()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName('Root')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)

        shell = QFrame()
        shell.setObjectName('Glass')
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(27, 60, 106, 120))
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)
        main = QVBoxLayout(shell)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(12)

        header = QHBoxLayout()
        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title_mark = QLabel()
        self.title_mark.setObjectName('TitleMark')
        self.title_mark.setFixedSize(4, 26)
        self.title = QLabel('洛克污染统计器')
        self.title.setObjectName('Title')
        title_row.addWidget(self.title_mark, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        self.subtitle = QLabel('Fluent Glass Monitor')
        self.subtitle.setObjectName('Subtitle')
        title_wrap.addLayout(title_row)
        title_wrap.addWidget(self.subtitle)
        self.status_dot = QLabel('●')
        self.status_text = QLabel('待机')
        self.topmost_pill = QLabel('置顶开启')
        self.topmost_pill.setObjectName('TopmostPill')
        self.time_label = QLabel('--:--')
        self.date_label = QLabel('-- ---')
        self.min_btn = QPushButton('—')
        self.min_btn.setObjectName('MinButton')
        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn = QPushButton('×')
        self.close_btn.setObjectName('CloseButton')
        self.close_btn.clicked.connect(self.close)
        header.addLayout(title_wrap, 1)
        header.addStretch(1)
        header.addWidget(self.topmost_pill)
        header.addSpacing(10)
        header.addWidget(self.status_dot)
        header.addWidget(self.status_text)
        header.addSpacing(16)
        header.addWidget(self.time_label)
        header.addWidget(self.date_label)
        header.addSpacing(10)
        header.addWidget(self.min_btn)
        header.addWidget(self.close_btn)
        main.addLayout(header)

        top = QHBoxLayout()
        top.setSpacing(12)
        main.addLayout(top)

        orb_panel = QFrame()
        orb_panel.setObjectName('Card')
        orb_layout = QVBoxLayout(orb_panel)
        self.orb = OrbWidget()
        orb_layout.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignCenter)
        orb_layout.addWidget(QLabel('累计统计', objectName='Caption'), 0, Qt.AlignmentFlag.AlignCenter)
        top.addWidget(orb_panel, 0)

        right = QFrame()
        right.setObjectName('Card')
        right_layout = QVBoxLayout(right)
        stats = QGridLayout()
        self.total_value = QLabel('0')
        self.species_value = QLabel('0')
        self.latest_value = QLabel('-')
        for idx, (name, widget) in enumerate([('总污染', self.total_value), ('种类', self.species_value), ('最新', self.latest_value)]):
            title = QLabel(name)
            title.setObjectName('MetaTitle')
            widget.setObjectName('MetaValue')
            stats.addWidget(title, 0, idx)
            stats.addWidget(widget, 1, idx)
        right_layout.addLayout(stats)

        row1 = QHBoxLayout()
        row2 = QHBoxLayout()
        self.start_btn = self._btn('开始', 'primary', self.start_realtime)
        self.stop_btn = self._btn('停止', 'secondary', self.stop_watch)
        self.capture_btn = self._btn('模板截图', 'neutral', self.capture_species_template)
        self.dir_btn = self._btn('目录', 'neutral', self.open_species_template_dir)
        self.reset_btn = self._btn('重置', 'warning', self.reset_stats)
        self.report_btn = self._btn('报表', 'neutral', self.open_report)
        for btn in (self.start_btn, self.stop_btn, self.capture_btn, self.dir_btn):
            row1.addWidget(btn)
        for btn in (self.reset_btn, self.report_btn):
            row2.addWidget(btn)
        row1.addStretch(1)
        row2.addStretch(1)
        self.topmost_check = QCheckBox('置顶')
        self.topmost_check.setChecked(True)
        self.topmost_check.toggled.connect(self.toggle_topmost)
        row2.addWidget(self.topmost_check)
        right_layout.addLayout(row1)
        right_layout.addLayout(row2)
        top.addWidget(right, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        main.addLayout(bottom, 1)

        log_panel = QFrame()
        log_panel.setObjectName('Card')
        log_layout = QVBoxLayout(log_panel)
        log_layout.addWidget(QLabel('日志输出', objectName='Section'))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName('LogText')
        log_layout.addWidget(self.log_text, 1)
        bottom.addWidget(log_panel, 1)

        pool_panel = QFrame()
        pool_panel.setObjectName('Card')
        pool_layout = QVBoxLayout(pool_panel)
        pool_layout.addWidget(QLabel('计数库', objectName='Section'))
        self.pool_table = QTableWidget(0, 3)
        self.pool_table.setHorizontalHeaderLabels(['名称', '计数', '污染'])
        self.pool_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.pool_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.pool_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.pool_table.verticalHeader().setVisible(False)
        self.pool_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pool_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.pool_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pool_table.setMouseTracking(True)
        self.pool_table.setAlternatingRowColors(True)
        self.pool_table.setShowGrid(False)
        pool_layout.addWidget(self.pool_table, 1)
        bottom.addWidget(pool_panel, 0)

        self.status_hint = QLabel('', shell)
        self.status_hint.setObjectName('StatusHint')
        self.status_hint.hide()
        self.status_hint_timer = QTimer(self)
        self.status_hint_timer.setSingleShot(True)
        self.status_hint_timer.timeout.connect(self.status_hint.hide)

        for btn in (self.start_btn, self.stop_btn, self.capture_btn, self.dir_btn, self.reset_btn, self.report_btn, self.min_btn, self.close_btn):
            self._add_button_shadow(btn)

    def _apply_styles(self):
        self.setStyleSheet("""
        #Root { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(122,182,238,220),stop:.45 rgba(152,207,255,215),stop:1 rgba(101,157,219,220)); }
        QFrame#Glass { background: rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.42); border-radius:22px; }
        QFrame#Card { background: rgba(255,255,255,.11); border:1px solid rgba(255,255,255,.24); border-radius:18px; }
        QLabel { color:#F8FBFF; background:transparent; }
        QLabel#TitleMark { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(237,251,255,.95),stop:1 rgba(137,219,255,.75)); border-radius:2px; }
        QLabel#Title { font:700 20pt 'Microsoft YaHei'; letter-spacing:.5px; }
        QLabel#Subtitle { font:500 9pt 'Segoe UI'; color:rgba(232,244,255,.68); padding-left:12px; }
        QLabel#Caption, QLabel#Section { font:600 11pt 'Microsoft YaHei'; }
        QLabel#MetaTitle { font:500 10pt 'Microsoft YaHei'; color:rgba(220,239,255,.78); }
        QLabel#MetaValue { font:700 18pt 'Microsoft YaHei'; }
        QLabel#TopmostPill { padding:5px 12px; border:1px solid rgba(255,255,255,.28); border-radius:12px; background:rgba(255,255,255,.10); color:rgba(246,252,255,.86); font:600 9pt 'Microsoft YaHei'; }
        QLabel#StatusHint { background:rgba(17,29,47,.84); border:1px solid rgba(191,227,255,.34); border-radius:14px; color:#F8FBFF; padding:8px 14px; font:600 10pt 'Microsoft YaHei'; }
        QTextEdit#LogText, QTableWidget { background:rgba(21,35,54,.52); border:1px solid rgba(198,226,255,.22); border-radius:12px; color:white; font:10pt 'Consolas'; padding:6px; gridline-color:rgba(195,223,255,.08); alternate-background-color:rgba(255,255,255,.035); selection-background-color:rgba(138,211,255,.12); }
        QTableWidget::item { border-bottom:1px solid rgba(255,255,255,.06); padding:7px 8px; }
        QTableWidget::item:hover { background:rgba(165,222,255,.10); }
        QHeaderView::section { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(246,250,255,.92),stop:1 rgba(211,226,244,.78)); color:#24405A; border:none; border-right:1px solid rgba(49,87,122,.16); padding:8px; font:600 10pt 'Microsoft YaHei'; }
        QPushButton { border-radius:14px; padding:12px 22px; color:white; font:700 11pt 'Microsoft YaHei'; border:1px solid rgba(255,255,255,.56); background-position:top; }
        QPushButton:hover { margin-top:1px; border-color:rgba(255,255,255,.76); }
        QPushButton:pressed { padding-top:15px; padding-bottom:9px; margin-top:2px; }
        QPushButton[role='primary'] { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(231,247,255,.98),stop:.18 rgba(141,219,255,.96),stop:.58 rgba(93,152,255,.96),stop:1 rgba(57,95,219,.98)); }
        QPushButton[role='secondary'] { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(248,235,255,.98),stop:.18 rgba(205,164,255,.96),stop:.58 rgba(145,111,232,.96),stop:1 rgba(96,74,176,.98)); }
        QPushButton[role='warning'] { color:#47300A; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,247,220,.98),stop:.18 rgba(248,217,118,.98),stop:.58 rgba(220,174,54,.98),stop:1 rgba(173,121,18,.98)); }
        QPushButton[role='neutral'] { color:#17324E; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(252,254,255,.98),stop:.18 rgba(228,237,248,.96),stop:.58 rgba(188,203,221,.96),stop:1 rgba(145,162,182,.98)); }
        QPushButton#MinButton, QPushButton#CloseButton { min-width:34px; max-width:34px; min-height:34px; max-height:34px; border-radius:17px; padding:0; font:700 14pt 'Segoe UI'; }
        QPushButton#MinButton { border:1px solid rgba(255,255,255,.22); background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,.20),stop:1 rgba(255,255,255,.06)); color:rgba(248,252,255,.95); }
        QPushButton#MinButton:hover { border:1px solid rgba(210,238,255,.58); background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(207,236,255,.44),stop:1 rgba(124,180,233,.20)); }
        QPushButton#MinButton:pressed { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(129,186,236,.42),stop:1 rgba(79,128,177,.26)); color:white; }
        QPushButton#CloseButton { border:1px solid rgba(255,255,255,.18); background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,.16),stop:1 rgba(255,255,255,.05)); color:rgba(248,252,255,.90); }
        QPushButton#CloseButton:hover { border:1px solid rgba(255,188,188,.64); background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,139,139,.96),stop:1 rgba(216,74,74,.94)); color:white; }
        QPushButton#CloseButton:pressed { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(198,64,64,.96),stop:1 rgba(152,34,34,.98)); color:white; }
        QCheckBox { color:white; font:500 10pt 'Microsoft YaHei'; }
        QCheckBox::indicator { width:18px; height:18px; border-radius:9px; border:1px solid rgba(255,255,255,.48); background:rgba(255,255,255,.18); }
        QCheckBox::indicator:checked { background:#9BD9FF; }
        QScrollBar:vertical { background:rgba(255,255,255,.08); width:10px; margin:6px 2px; border-radius:5px; }
        QScrollBar::handle:vertical { background:rgba(223,242,255,.6); border-radius:5px; min-height:24px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
        """)

    def _btn(self, text, role, slot):
        btn = QPushButton(text)
        btn.setProperty('role', role)
        btn.clicked.connect(slot)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        return btn

    def _add_button_shadow(self, widget, blur=20, y_offset=6):
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(blur)
        effect.setOffset(0, y_offset)
        effect.setColor(QColor(20, 47, 82, 110))
        widget.setGraphicsEffect(effect)

    def _show_hint(self, text, timeout_ms=1800):
        self.status_hint.setText(text)
        self.status_hint.adjustSize()
        width = min(self.status_hint.width() + 12, max(260, self.width() - 80))
        self.status_hint.resize(width, self.status_hint.height() + 8)
        self.status_hint.move(self.width() - self.status_hint.width() - 34, 72)
        self.status_hint.show()
        self.status_hint.raise_()
        self.status_hint_timer.start(timeout_ms)

    def _tick_clock(self):
        now = time.localtime()
        self.time_label.setText(time.strftime('%H:%M', now))
        self.date_label.setText(time.strftime('%d %B', now))

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip('洛克污染统计器')

        self.tray_menu = QMenu()
        act_toggle = QAction('显示/隐藏', self)
        act_toggle.triggered.connect(self._toggle_visible)
        act_start = QAction('开始实时识别', self)
        act_start.triggered.connect(self.start_realtime)
        act_stop = QAction('停止识别', self)
        act_stop.triggered.connect(self.stop_watch)
        act_capture = QAction('模板截图 (Ctrl+Alt+T)', self)
        act_capture.triggered.connect(self.capture_species_template)
        act_quit = QAction('退出', self)
        act_quit.triggered.connect(self._quit_from_tray)

        self.tray_menu.addAction(act_toggle)
        self.tray_menu.addAction(act_start)
        self.tray_menu.addAction(act_stop)
        self.tray_menu.addAction(act_capture)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(act_quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    def _toggle_visible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _show_main_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _setup_global_hotkey(self):
        if sys.platform != 'win32':
            return
        try:
            self.hotkey_filter = WinHotkeyFilter(self._on_capture_hotkey)
            QApplication.instance().installNativeEventFilter(self.hotkey_filter)
            user32 = ctypes.windll.user32
            mod = 0x0001 | 0x0002
            vk_t = 0x54
            self.hotkey_registered = bool(user32.RegisterHotKey(None, 1, mod, vk_t))
            if self.hotkey_registered:
                self.bridge.log.emit('全局热键已启用: Ctrl+Alt+T')
            else:
                self.bridge.log.emit('全局热键注册失败')
        except Exception as exc:
            self.bridge.log.emit(f'全局热键异常: {exc}')

    def _setup_floating_orb(self):
        self.floating_orb = FloatingOrbWindow()
        self.floating_orb.singleClicked.connect(self._toggle_visible)
        self.floating_orb.doubleClicked.connect(self._toggle_start_stop)
        self.floating_orb.captureRequested.connect(self.capture_species_template)
        self.floating_orb.openDirRequested.connect(self.open_species_template_dir)
        self.floating_orb.showMainRequested.connect(self._show_main_window)
        self.floating_orb.topmostToggled.connect(self._set_topmost_checked)
        self.floating_orb.quitRequested.connect(self._quit_from_tray)
        self.floating_orb.positionChanged.connect(self._save_orb_position)
        self.floating_orb.bind_start_stop(self.start_realtime, self.stop_watch)
        self.floating_orb.set_topmost_enabled(self.topmost_check.isChecked())
        self.floating_orb.set_running_actions(self.running)
        pool = self.state.get('pet_pool', {})
        recs = self.state.get('records', [])
        latest = recs[-1].get('pet_name') if recs else '-'
        self.floating_orb.set_data(str(self.state.get('total_pollution', 0)), latest or '-', len(pool), self.session_hits)
        init_color = '#8DE0FF' if self.running else '#8C98A7'
        self.floating_orb.set_status(self.status_text.text(), init_color, self.battle_locked_state)
        orb_cfg = self._orb_cfg()
        self.floating_orb.set_saved_position(orb_cfg.get('x'), orb_cfg.get('y'), orb_cfg.get('dock_side'))
        self.floating_orb.show()

    def _on_capture_hotkey(self):
        if self.overlay is not None:
            return
        QTimer.singleShot(0, self.capture_species_template)

    def _toggle_start_stop(self):
        if self.running:
            self.stop_watch()
        else:
            self.start_realtime()

    def _set_topmost_checked(self, enabled: bool):
        self.topmost_check.setChecked(bool(enabled))

    def _flash_floating_orb(self):
        if self.floating_orb is not None:
            self.floating_orb.flash_hit()

    def _notify_orb_hit(self, pet_name: str):
        if self.floating_orb is not None:
            self.floating_orb.notify_hit(pet_name, self.session_hits)

    def _orb_cfg(self):
        return self.cfg.setdefault('floating_orb', {
            'x': None,
            'y': None,
            'dock_side': 'right',
        })

    def _save_orb_position(self, x: int, y: int, dock_side: str):
        orb_cfg = self._orb_cfg()
        orb_cfg['x'] = int(x)
        orb_cfg['y'] = int(y)
        orb_cfg['dock_side'] = dock_side
        tracker.save_json(tracker.CONFIG_PATH, self.cfg)

    def _unregister_hotkey(self):
        if sys.platform == 'win32' and self.hotkey_registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(None, 1)
            except Exception:
                pass
            self.hotkey_registered = False
        if self.hotkey_filter is not None:
            try:
                QApplication.instance().removeNativeEventFilter(self.hotkey_filter)
            except Exception:
                pass
            self.hotkey_filter = None

    def _quit_from_tray(self):
        self._quitting = True
        self.stop_event.set()
        self.close()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and self.tray is not None:
            QTimer.singleShot(0, self.hide)
            self.tray.showMessage('洛克污染统计器', '已最小化到托盘', QSystemTrayIcon.MessageIcon.Information, 1200)
    def _append_log(self, text):
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        self.logs.append(line)
        self.logs = self.logs[-500:]
        self.log_text.setPlainText('\n'.join(self.logs))
        self.log_text.moveCursor(self.log_text.textCursor().MoveOperation.End)
        if any(key in text for key in ('开始', '停止', '模板', '保存', '取消', '置顶', '异常')):
            self._show_hint(text[:48])

    def _set_status(self, text, color):
        self.status_text.setText(text)
        self.status_dot.setStyleSheet(f'color:{color}; background:transparent;')
        self.topmost_pill.setText('置顶开启' if self.topmost_check.isChecked() else '置顶关闭')
        if self.floating_orb is not None:
            self.floating_orb.set_status(text, color, self.battle_locked_state)
            self.floating_orb.set_topmost_enabled(self.topmost_check.isChecked())
            self.floating_orb.set_running_actions(self.running)

    def refresh_stats(self):
        total = str(self.state.get('total_pollution', 0))
        pool = self.state.get('pet_pool', {})
        recs = self.state.get('records', [])
        latest = recs[-1].get('pet_name') if recs else '-'
        self.total_value.setText(total)
        self.species_value.setText(str(len(pool)))
        self.latest_value.setText(latest or '-')
        self.orb.set_value(total)
        if self.floating_orb is not None:
            self.floating_orb.set_data(total, latest or '-', len(pool), self.session_hits)
        self.pool_table.setRowCount(0)
        rows = []
        for name, info in pool.items():
            cnt = int(info.get('count', 0)) if isinstance(info, dict) else int(info)
            pol = int(info.get('pollution', cnt)) if isinstance(info, dict) else cnt
            rows.append((name, cnt, pol))
        rows.sort(key=lambda x: (x[2], x[1]), reverse=True)
        for r, (name, cnt, pol) in enumerate(rows):
            self.pool_table.insertRow(r)
            for c, v in enumerate((name, str(cnt), str(pol))):
                item = QTableWidgetItem(v)
                item.setForeground(QColor('#F8FBFF'))
                if r % 2 == 0:
                    item.setBackground(QColor(255, 255, 255, 8))
                self.pool_table.setItem(r, c, item)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseReleaseEvent(self, _event):
        self.drag_pos = None

    def closeEvent(self, event):
        if self.tray is not None and self.tray.isVisible() and not self._quitting:
            event.ignore()
            self.hide()
            self.tray.showMessage('洛克污染统计器', '程序仍在后台运行', QSystemTrayIcon.MessageIcon.Information, 1200)
            return
        self.stop_event.set()
        self._unregister_hotkey()
        if self.tray is not None:
            self.tray.hide()
        if self.overlay is not None:
            self.overlay.close()
            self.overlay.deleteLater()
            self.overlay = None
        if self.floating_orb is not None:
            self._save_orb_position(self.floating_orb.x(), self.floating_orb.y(), self.floating_orb.dock_side)
            self.floating_orb.close()
            self.floating_orb.deleteLater()
            self.floating_orb = None
        self.tray = None
        self.tray_menu = None
        self.hotkey_filter = None
        self.hotkey_registered = False
        self._quitting = False
        tracker.save_json(tracker.STATE_PATH, self.state)
        super().closeEvent(event)

    def _load_species_templates(self):
        self.species_templates = []
        template_dir = Path((self.cfg.get('species_template_mode', {}) or {}).get('template_dir', str(tracker.SPECIES_TEMPLATE_DIR)))
        template_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted(template_dir.glob('*')):
            if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
                img = tracker.read_image(p)
                if img is not None and img.size:
                    self.species_templates.append({'name': p.stem, 'image': tracker.crop_template_to_icon(img, self.cfg.get('icon_mode', {}))})

    def _load_species_db(self):
        nm = self.cfg.get('name_mode', {}) or {}
        db_path = Path(nm.get('species_db_path', str(tracker.ROOT / 'species_names.json')))
        self.species_names = []
        self.species_alias = {}
        if not db_path.exists():
            return
        try:
            data = json.loads(db_path.read_text(encoding='utf-8'))
            if isinstance(data, list):
                self.species_names = [self._fix_text(x).strip() for x in data if str(x).strip()]
            elif isinstance(data, dict):
                names = data.get('names', [])
                aliases = data.get('aliases', {})
                self.species_names = [self._fix_text(x).strip() for x in names if str(x).strip()]
                self.species_alias = {
                    self._fix_text(k).strip(): self._fix_text(v).strip()
                    for k, v in aliases.items()
                    if str(k).strip() and str(v).strip()
                }
        except Exception:
            self.species_names = []
            self.species_alias = {}

    @staticmethod
    def _fix_text(s):
        s = str(s)
        if any('\u4e00' <= ch <= '\u9fff' for ch in s):
            return s
        try:
            fixed = s.encode('gbk', errors='ignore').decode('utf-8', errors='ignore')
            if fixed and fixed != s:
                return fixed
        except Exception:
            pass
        return s

    def _get_name_engine(self):
        if self.name_engine is not None:
            return self.name_engine
        if tracker.RapidOCR is None:
            self.name_engine = None
            return None
        try:
            self.name_engine = tracker.RapidOCR()
        except Exception:
            self.name_engine = None
        return self.name_engine

    def _known_species_names(self):
        known = []
        seen = set()
        for name in self.species_names:
            n = str(name).strip()
            if n and n not in seen:
                known.append(n)
                seen.add(n)
        for name in self.species_alias.values():
            n = str(name).strip()
            if n and n not in seen:
                known.append(n)
                seen.add(n)
        for item in self.species_templates:
            n = str(item.get('name', '')).strip()
            if n and n not in seen:
                known.append(n)
                seen.add(n)
        return known

    def _best_species_match(self, text):
        if not text:
            return None, 0.0
        threshold = float((self.cfg.get('name_mode', {}) or {}).get('fuzzy_threshold', 0.62))
        normalized_text = tracker.normalize_species_name_text(text)
        for wrong, right in self.species_alias.items():
            wrong_norm = tracker.normalize_species_name_text(wrong)
            if wrong_norm and wrong_norm in normalized_text:
                return right, 1.0
        best_name = None
        best_score = 0.0
        for name in self._known_species_names():
            name_norm = tracker.normalize_species_name_text(name)
            if not name_norm:
                continue
            if name_norm in normalized_text:
                return name, 1.0
            score = tracker.similarity_ratio(normalized_text, name_norm)
            if score > best_score:
                best_score = score
                best_name = name
        if best_name and best_score >= threshold:
            return best_name, best_score
        return None, best_score

    @staticmethod
    def _extract_pet_candidates(raw_text):
        text = (raw_text or '').replace('\n', ' ')
        text = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9路]', ' ', text)
        tokens = [t.strip() for t in text.split() if t.strip()]
        out = []
        for token in tokens:
            token = token.replace('♀', '').replace('♂', '').strip()
            if not token:
                continue
            if token.endswith('级'):
                token = token[:-1].strip()
            if not token or re.fullmatch(r'\d+', token):
                continue
            if re.fullmatch(r'[\u4e00-\u9fa5路]{2,8}', token):
                out.append(token)
            elif re.fullmatch(r'[A-Za-z][A-Za-z0-9路]{1,15}', token):
                out.append(token)
        return out

    def _ocr_name_from_roi(self, roi_bgr):
        engine = self._get_name_engine()
        if engine is None or roi_bgr is None or roi_bgr.size == 0:
            return None, ''
        texts = []
        up = cv2.resize(roi_bgr, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
        texts.append(tracker.run_ocr_on_bgr(engine, up))
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        if not texts[0].strip():
            _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            texts.append(tracker.run_ocr_on_bgr(engine, cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)))
        if not any(t.strip() for t in texts):
            ad = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
            texts.append(tracker.run_ocr_on_bgr(engine, cv2.cvtColor(ad, cv2.COLOR_GRAY2BGR)))
        candidates = []
        for text in texts:
            candidates.extend(self._extract_pet_candidates(text))
        merged = ' '.join([x for x in texts if x] + candidates)
        matched_name, _ = self._best_species_match(merged)
        if matched_name:
            return matched_name, merged[:200]
        chinese_candidates = [
            x for x in candidates
            if re.fullmatch(r'[\u4e00-\u9fa5路]{2,8}', x) and x not in self.NAME_BLACKLIST
        ]
        if chinese_candidates:
            guess = collections.Counter(chinese_candidates).most_common(1)[0][0]
            min_len = int((self.cfg.get('name_mode', {}) or {}).get('min_ocr_text_length', 2))
            if len(guess) >= min_len:
                return guess, merged[:200]
        return None, merged[:200]

    @staticmethod
    def _crop_name_region(frame_bgr, name_cfg):
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        h, w = frame_bgr.shape[:2]
        region_cfg = (name_cfg.get('region', {}) or {})
        x_ratio = float(region_cfg.get('x_ratio', 0.79))
        y_ratio = float(region_cfg.get('y_ratio', 0.015))
        w_ratio = float(region_cfg.get('w_ratio', 0.16))
        h_ratio = float(region_cfg.get('h_ratio', 0.085))
        x1 = max(0, min(int(w * x_ratio), w - 1))
        y1 = max(0, min(int(h * y_ratio), h - 1))
        x2 = max(x1 + 1, min(int(w * (x_ratio + w_ratio)), w))
        y2 = max(y1 + 1, min(int(h * (y_ratio + h_ratio)), h))
        return frame_bgr[y1:y2, x1:x2]

    def _recognize_species_name(self, frame_bgr):
        name_cfg = self.cfg.get('name_mode', {}) or {}
        if not bool(name_cfg.get('enabled', True)):
            return None, 'name=off', ''
        roi = self._crop_name_region(frame_bgr, name_cfg)
        if roi is None or roi.size == 0:
            return None, 'name=roi-empty', ''
        name, raw_text = self._ocr_name_from_roi(roi)
        if not name:
            return None, f"name=reject raw={raw_text[:40] or '-'}", raw_text
        name = str(name).strip()
        if name in self.UNKNOWN_PET_NAMES or name in self.NAME_BLACKLIST:
            return None, f'name=reject bad={name}', raw_text
        return name, f'name=ok:{name}', raw_text

    def _recognize_species_name_cached(self, frame_bgr, now, force=False):
        name_cfg = self.cfg.get('name_mode', {}) or {}
        ocr_interval = max(float(name_cfg.get('ocr_interval_sec', 0.9)), 0.15)
        cache_ttl = max(float(name_cfg.get('cache_ttl_sec', 2.4)), 0.0)
        if not force and self._name_cache_name and (now - self._name_cache_ts) <= cache_ttl:
            return self._name_cache_name, f"{self._name_cache_reason}|cache", self._name_cache_raw
        if not force and (now - self._name_last_ocr_ts) < ocr_interval:
            return None, f"name=throttle(wait={ocr_interval - (now - self._name_last_ocr_ts):.2f}s)", self._name_cache_raw
        self._name_last_ocr_ts = now
        name, reason, raw_text = self._recognize_species_name(frame_bgr)
        if name:
            self._name_cache_name = name
            self._name_cache_reason = reason
            self._name_cache_raw = raw_text
            self._name_cache_ts = now
            return name, reason, raw_text
        if (now - self._name_cache_ts) <= cache_ttl and self._name_cache_name:
            return self._name_cache_name, f"{reason}|stale-cache", raw_text or self._name_cache_raw
        self._name_cache_raw = raw_text
        return None, reason, raw_text

    def _load_attribute_templates(self):
        self.attribute_templates = []
        self.species_attribute_map = {}
        attr_cfg = self.cfg.get('attribute_mode', {}) or {}
        template_dir = Path(attr_cfg.get('template_dir', str(tracker.ATTRIBUTE_TEMPLATE_DIR)))
        template_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted(template_dir.glob('*')):
            if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
                img = tracker.read_image(p)
                if img is not None and img.size:
                    self.attribute_templates.append({'name': p.stem, 'image': img})

        map_path = Path(attr_cfg.get('species_attribute_map_path', str(tracker.SPECIES_ATTRIBUTE_PATH)))
        data = tracker.load_json(map_path, {})
        parsed = {}
        if isinstance(data, dict):
            for k, v in data.items():
                name = str(k).strip()
                if not name:
                    continue
                if isinstance(v, list):
                    attrs = [str(x).strip() for x in v if str(x).strip()]
                else:
                    attrs = [str(v).strip()] if str(v).strip() else []
                if attrs:
                    parsed[name] = attrs
        self.species_attribute_map = parsed

    def save_settings(self):
        self._orb_cfg()
        tracker.save_json(tracker.CONFIG_PATH, self.cfg)
        self._load_species_db()
        self._load_species_templates()
        self._load_attribute_templates()
        self.bridge.log.emit(f"设置已保存：dir={self.cfg.get('watch_dir')}, interval={self.cfg.get('poll_interval_sec')}s")
        return True

    @staticmethod
    def _crop_attr_roi(frame_bgr, bbox, attr_cfg):
        x, y, w, h = bbox
        roi_cfg = (attr_cfg.get('roi', {}) or {})
        x_ratio = float(roi_cfg.get('x_ratio', -0.42))
        y_ratio = float(roi_cfg.get('y_ratio', 0.52))
        w_ratio = float(roi_cfg.get('w_ratio', 0.62))
        h_ratio = float(roi_cfg.get('h_ratio', 0.56))
        fh, fw = frame_bgr.shape[:2]
        x1 = int(x + w * x_ratio)
        y1 = int(y + h * y_ratio)
        x2 = int(x + w * (x_ratio + w_ratio))
        y2 = int(y + h * (y_ratio + h_ratio))
        x1 = max(0, min(x1, fw - 1))
        y1 = max(0, min(y1, fh - 1))
        x2 = max(x1 + 1, min(x2, fw))
        y2 = max(y1 + 1, min(y2, fh))
        return frame_bgr[y1:y2, x1:x2]

    def _detect_attributes(self, frame_bgr, bbox):
        attr_cfg = self.cfg.get('attribute_mode', {}) or {}
        if not bool(attr_cfg.get('enabled', True)):
            return [], {}
        if not self.attribute_templates:
            return [], {}
        roi = self._crop_attr_roi(frame_bgr, bbox, attr_cfg)
        if roi is None or roi.size == 0:
            return [], {}
        min_score = float(attr_cfg.get('min_match_score', 0.62))
        scales = attr_cfg.get('scales', [0.9, 1.0, 1.1]) or [1.0]
        best_scores = {}
        for tpl in self.attribute_templates:
            tmpl = tpl['image']
            if tmpl is None or tmpl.size == 0:
                continue
            best = 0.0
            for sc in scales:
                try:
                    sc = float(sc)
                except Exception:
                    continue
                if sc <= 0:
                    continue
                if abs(sc - 1.0) < 1e-3:
                    t = tmpl
                else:
                    tw = max(10, int(round(tmpl.shape[1] * sc)))
                    th = max(10, int(round(tmpl.shape[0] * sc)))
                    t = cv2.resize(tmpl, (tw, th), interpolation=cv2.INTER_LINEAR)
                if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
                    continue
                res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
                if res is None or res.size == 0:
                    continue
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val > best:
                    best = float(max_val)
            best_scores[tpl['name']] = best
        matched = [k for k, v in best_scores.items() if v >= min_score]
        matched.sort(key=lambda n: best_scores.get(n, 0.0), reverse=True)
        return matched, best_scores

    def _verify_attribute_gate(self, frame_bgr, match):
        attr_cfg = self.cfg.get('attribute_mode', {}) or {}
        if not bool(attr_cfg.get('enabled', True)):
            return True, 'attr=off'
        if not self.attribute_templates:
            if bool(attr_cfg.get('require_attribute_template', True)):
                return False, 'attr=reject(no-templates)'
            return True, 'attr=skip(no-templates)'
        name = str(match.get('name', '') or '').strip()
        expected = self.species_attribute_map.get(name, [])
        if not expected:
            if bool(attr_cfg.get('require_species_map', True)):
                return False, 'attr=reject(no-map)'
            return True, 'attr=skip(no-map)'
        bbox = match.get('bbox', (0, 0, 0, 0))
        matched, scores = self._detect_attributes(frame_bgr, bbox)
        if not matched:
            top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:2]
            top_s = ','.join([f'{k}:{v:.2f}' for k, v in top]) if top else '-'
            return False, f"attr=miss expected={expected} top={top_s}"
        expected_set = {str(x).strip() for x in expected if str(x).strip()}
        matched_set = {str(x).strip() for x in matched if str(x).strip()}
        inter = expected_set.intersection(matched_set)
        if inter:
            return True, f"attr=ok expected={list(expected_set)} got={matched[:2]}"
        return False, f"attr=reject expected={list(expected_set)} got={matched[:2]}"

    def _match_species_template(self, frame_bgr, allowed_names=None):
        best_hit = None
        best_hit_score = -1.0
        second_hit_score = -1.0
        best_any = None
        best_any_score = -1.0
        second_any_score = -1.0
        allowed_set = None
        if allowed_names is not None:
            allowed_set = {str(x).strip() for x in allowed_names if str(x).strip()}
            if not allowed_set:
                return None
        base_cfg = dict(self.cfg.get('icon_mode', {}))
        base_cfg['use_template'] = True
        species_cfg = self.cfg.get('species_template_mode', {}) or {}
        base_cfg['template_match_threshold'] = float(
            species_cfg.get('match_threshold', base_cfg.get('template_match_threshold', 0.70))
        )
        base_cfg['purple_ratio_threshold'] = float(
            species_cfg.get('purple_ratio_threshold', base_cfg.get('purple_ratio_threshold', 0.20))
        )
        # Species template matching is already stricter than single-icon matching.
        # Disable IoU gate here to reduce dark-scene false negatives.
        base_cfg['enable_mask_iou_gate'] = bool(species_cfg.get('enable_mask_iou_gate', False))
        for item in self.species_templates:
            if allowed_set is not None and str(item.get('name', '')).strip() not in allowed_set:
                continue
            hit, score, ratio, reason, bbox = tracker.detect_purple_icon_in_frame_with_bbox(frame_bgr, base_cfg, item['image'])
            cand = {
                'name': item['name'],
                'score': float(score),
                'ratio': float(ratio),
                'reason': reason,
                'countable': bool(hit),
                'fallback': False,
                'bbox': bbox,
            }
            if score > best_any_score:
                second_any_score = best_any_score
                best_any_score = score
                best_any = cand
            elif score > second_any_score:
                second_any_score = score
            if hit and score > best_hit_score:
                second_hit_score = best_hit_score
                best_hit_score = score
                best_hit = cand
            elif hit and score > second_hit_score:
                second_hit_score = score
        margin_th = float(species_cfg.get('second_best_margin', 0.06))
        if best_hit is not None:
            margin = float(best_hit_score - max(second_hit_score, 0.0))
            if margin < margin_th:
                best_hit['countable'] = False
                best_hit['reason'] = f"{best_hit.get('reason', '')}|name-ambiguous(margin={margin:.3f})"
                return best_hit
            ok, attr_reason = self._verify_attribute_gate(frame_bgr, best_hit)
            best_hit['reason'] = f"{best_hit.get('reason', '')}|{attr_reason}"
            if not ok:
                best_hit['countable'] = False
            return best_hit
        # Keep best candidate for debug logs, but do not count near-miss as hit.
        if best_any is not None:
            debug_best_min_score = float(species_cfg.get('debug_best_min_score', species_cfg.get('match_threshold', 0.58)))
            if float(best_any.get('score', 0.0)) < debug_best_min_score:
                best_any['countable'] = False
                best_any['reason'] = (
                    f"{best_any.get('reason', '')}|near-miss(score={best_any.get('score', 0.0):.3f}"
                    f"<debug={debug_best_min_score:.3f})"
                )
                return best_any
            margin = float(best_any_score - max(second_any_score, 0.0))
            if margin < margin_th:
                best_any['countable'] = False
                best_any['reason'] = f"{best_any.get('reason', '')}|best-ambiguous(margin={margin:.3f})"
                return best_any
            _, attr_reason = self._verify_attribute_gate(frame_bgr, best_any)
            best_any['reason'] = f"{best_any.get('reason', '')}|{attr_reason}"
            best_any['countable'] = False
        return best_any

    @staticmethod
    def _crop_search_region(frame_bgr, screen_cfg, region_cfg_override=None):
        h, w = frame_bgr.shape[:2]
        region_cfg = region_cfg_override if region_cfg_override is not None else (screen_cfg.get('search_region', {}) or {})
        x_ratio = float(region_cfg.get('x_ratio', 0.0))
        y_ratio = float(region_cfg.get('y_ratio', 0.0))
        w_ratio = float(region_cfg.get('w_ratio', 0.48))
        h_ratio = float(region_cfg.get('h_ratio', 0.36))
        x1 = max(0, min(int(w * x_ratio), w - 1))
        y1 = max(0, min(int(h * y_ratio), h - 1))
        x2 = max(x1 + 1, min(int(w * (x_ratio + w_ratio)), w))
        y2 = max(y1 + 1, min(int(h * (y_ratio + h_ratio)), h))
        return frame_bgr[y1:y2, x1:x2], (x1, y1)

    @staticmethod
    def _crop_local_track_region(frame_bgr, bbox, expand_ratio):
        if frame_bgr is None or frame_bgr.size == 0 or not bbox:
            return None, (0, 0)
        x, y, w, h = [int(v) for v in bbox]
        if w <= 0 or h <= 0:
            return None, (0, 0)
        fh, fw = frame_bgr.shape[:2]
        cx = x + w / 2.0
        cy = y + h / 2.0
        half_w = max(int(round(w * expand_ratio / 2.0)), 18)
        half_h = max(int(round(h * expand_ratio / 2.0)), 18)
        x1 = max(0, int(round(cx - half_w)))
        y1 = max(0, int(round(cy - half_h)))
        x2 = min(fw, int(round(cx + half_w)))
        y2 = min(fh, int(round(cy + half_h)))
        if x2 <= x1 or y2 <= y1:
            return None, (0, 0)
        return frame_bgr[y1:y2, x1:x2], (x1, y1)

    @staticmethod
    def _offset_match_bbox(match, offset_xy):
        if match is None:
            return None
        ox, oy = offset_xy
        bbox = match.get('bbox', (0, 0, 0, 0))
        x, y, w, h = [int(v) for v in bbox]
        out = dict(match)
        out['bbox'] = (x + int(ox), y + int(oy), w, h)
        return out

    def _realtime_loop(self):
        try:
            tracker.require_screen_tools()
            screen_cfg = self.cfg.get('screen_mode', {})
            icon_cfg = dict(self.cfg.get('icon_mode', {}))
            name_cfg = self.cfg.get('name_mode', {}) or {}
            icon_cfg['use_template'] = True
            self._load_species_db()
            self._load_species_templates()
            self._load_attribute_templates()
            if not self.species_templates:
                raise RuntimeError('未找到精灵模板。请先截取模板。')
            require_name_match = bool(name_cfg.get('require_name_match', True))
            prefer_ocr_name_first = bool(name_cfg.get('prefer_ocr_name_first', True))
            self.bridge.log.emit(
                f"实时识别模式：名字 OCR 优先，共加载 {len(self.species_templates)} 个模板，"
                f"名字门槛={'开启' if require_name_match else '关闭'}"
            )
            interval = max(float(screen_cfg.get('capture_interval_sec', 0.7)), 0.6)
            min_gap = float(screen_cfg.get('min_trigger_gap_sec', 1.2))
            rearm_absent_sec = float(screen_cfg.get('rearm_absent_sec', 3.0))
            icon_value = int(icon_cfg.get('icon_pollution_value', 1))
            window_hint = str(screen_cfg.get('window_title_contains', '') or '')
            species_cfg = self.cfg.get('species_template_mode', {}) or {}
            local_track_enabled = bool(species_cfg.get('local_track_enabled', True))
            local_track_expand_ratio = max(float(species_cfg.get('local_track_expand_ratio', 1.8)), 1.15)
            full_scan_interval = max(float(species_cfg.get('full_scan_interval_sec', 1.2)), interval)
            last_trigger_ts = 0.0
            last_info_ts = 0.0
            battle_locked = False
            absent_since_ts = None
            with tracker.mss.mss() as sct:
                warned = False
                while not self.stop_event.is_set():
                    region = tracker._find_window_rect(window_hint)
                    if not region:
                        if not warned:
                            self.bridge.log.emit('未找到游戏窗口，实时识别已暂停。')
                            warned = True
                        time.sleep(interval)
                        continue
                    warned = False
                    frame = np.array(sct.grab(region))
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    now = time.time()
                    force_name_ocr = not battle_locked
                    recognized_name, name_reason, raw_name_text = self._recognize_species_name_cached(
                        frame_bgr, now, force=force_name_ocr and (now - self._name_last_ocr_ts >= float(name_cfg.get('ocr_interval_sec', 0.9)))
                    )
                    allowed_names = [recognized_name] if recognized_name else []
                    search_bgr, _ = self._crop_search_region(frame_bgr, screen_cfg)
                    match = None
                    match_region = 'main'
                    if recognized_name:
                        used_local_track = False
                        if (
                            local_track_enabled
                            and self._tracked_species_name == recognized_name
                            and self._tracked_species_bbox is not None
                        ):
                            local_bgr, local_offset = self._crop_local_track_region(
                                search_bgr, self._tracked_species_bbox, local_track_expand_ratio
                            )
                            if local_bgr is not None:
                                local_match = self._match_species_template(local_bgr, allowed_names=allowed_names)
                                if local_match is not None:
                                    match = self._offset_match_bbox(local_match, local_offset)
                                    match_region = 'local'
                                    used_local_track = True
                        need_full_scan = (
                            match is None
                            or not bool(match.get('countable', False))
                            or (now - self._last_full_scan_ts >= full_scan_interval)
                        )
                        if need_full_scan:
                            full_match = self._match_species_template(search_bgr, allowed_names=allowed_names)
                            self._last_full_scan_ts = now
                            if full_match is not None and (match is None or full_match.get('score', 0.0) >= match.get('score', 0.0)):
                                match = full_match
                                match_region = 'main'
                        fallback_region_cfg = screen_cfg.get('search_region_fallback', {
                            'x_ratio': 0.50,
                            'y_ratio': 0.0,
                            'w_ratio': 0.50,
                            'h_ratio': 0.30,
                        }) or {}
                        if (not used_local_track) and ((match is None) or (not bool(match.get('countable', False)))):
                            fb_bgr, _ = self._crop_search_region(frame_bgr, screen_cfg, fallback_region_cfg)
                            fb_match = self._match_species_template(fb_bgr, allowed_names=allowed_names)
                            if fb_match is not None and (match is None or fb_match.get('score', 0.0) > match.get('score', 0.0)):
                                match = fb_match
                                match_region = 'fallback'
                    elif not require_name_match and not prefer_ocr_name_first:
                        match = self._match_species_template(search_bgr)
                    countable = bool(match and match.get('countable', False))
                    if require_name_match and not recognized_name:
                        countable = False
                    if match is not None and recognized_name == match.get('name'):
                        self._tracked_species_name = recognized_name
                        self._tracked_species_bbox = match.get('bbox')
                        self._tracked_species_ts = now
                    if countable and (now - last_trigger_ts >= min_gap):
                        absent_since_ts = None
                        if not battle_locked:
                            pet_name = recognized_name or match['name']
                            last_trigger_ts = now
                            battle_locked = True
                            self.battle_locked_state = True
                            self.state['total_pollution'] = int(self.state.get('total_pollution', 0)) + icon_value
                            self.session_hits += icon_value
                            pool = self.state.setdefault('pet_pool', {})
                            item = pool.setdefault(pet_name, {'count': 0, 'pollution': 0})
                            item['count'] += 1
                            item['pollution'] += icon_value
                            self.state.setdefault('records', []).append({'time': int(now), 'pet_name': pet_name})
                            tracker.save_json(tracker.STATE_PATH, self.state)
                            fb_tag = ' (dark-fallback)' if match.get('fallback', False) else ''
                            self.bridge.log.emit(
                                f"实时触发 +{icon_value} | 精灵={pet_name}{fb_tag} | region={match_region} "
                                f"| score={match['score']:.3f} purple={match['ratio']:.3f} "
                                f"| {name_reason}|{match.get('reason', '')}"
                            )
                            self.bridge.status.emit('实时识别中', '#8DE0FF')
                            self.bridge.stats.emit()
                            self.bridge.orbFlash.emit()
                            self.bridge.orbHit.emit(pet_name)
                    elif not countable:
                        if absent_since_ts is None:
                            absent_since_ts = now
                        elif battle_locked and now - absent_since_ts >= rearm_absent_sec:
                            battle_locked = False
                            self.battle_locked_state = False
                            self._name_cache_name = None
                            self._name_cache_reason = 'name=reset'
                            self._name_cache_raw = ''
                            self._name_cache_ts = 0.0
                            self._tracked_species_name = None
                            self._tracked_species_bbox = None
                            self._tracked_species_ts = 0.0
                            self.bridge.status.emit('实时识别中', '#8DE0FF')
                    if now - last_info_ts >= 2.0:
                        if countable:
                            fb_tag = ' fallback' if match.get('fallback', False) else ''
                            self.bridge.log.emit(
                                f"实时状态 hit=True{fb_tag} region={match_region} pet={match['name']} "
                                f"score={match['score']:.3f} purple={match['ratio']:.3f} {name_reason}"
                            )
                        elif require_name_match and not recognized_name:
                            raw_hint = raw_name_text[:40] if raw_name_text else '-'
                            self.bridge.log.emit(f'实时状态 hit=False {name_reason} raw={raw_hint}')
                        elif match is not None:
                            self.bridge.log.emit(
                                f"实时状态 hit=False best={match['name']} region={match_region} "
                                f"score={match['score']:.3f} purple={match['ratio']:.3f} reason={name_reason}|{match.get('reason', '')}"
                            )
                        else:
                            self.bridge.log.emit(f'实时状态 hit=False {name_reason}')
                        last_info_ts = now
                    time.sleep(interval)
        except Exception as exc:
            self.bridge.error.emit('实时识别异常', str(exc))
        finally:
            self.running = False
            self.battle_locked_state = False
            self.bridge.status.emit('待机', '#8C98A7')

    def start_realtime(self):
        if self.running:
            self.bridge.log.emit('已有模式在运行，请先停止')
            return
        self.save_settings()
        self.stop_event.clear()
        self.running = True
        self.battle_locked_state = False
        self.bridge.status.emit('实时识别中', '#8DE0FF')
        if self.floating_orb is not None:
            self.floating_orb.set_running_actions(True)
        self.worker = threading.Thread(target=self._realtime_loop, daemon=True)
        self.worker.start()
        self.bridge.log.emit('开始实时识别')

    def stop_watch(self):
        if not self.running:
            self.bridge.log.emit('当前未运行')
            return
        self.stop_event.set()
        self.running = False
        self.battle_locked_state = False
        tracker.save_json(tracker.STATE_PATH, self.state)
        self.bridge.status.emit('待机', '#8C98A7')
        if self.floating_orb is not None:
            self.floating_orb.set_running_actions(False)
        self.bridge.log.emit('已停止实时识别')

    def reset_stats(self):
        if QMessageBox.question(self, '确认', '确定要重置统计吗？') != QMessageBox.StandardButton.Yes:
            return
        tracker.command_reset()
        self.state = tracker.load_json(tracker.STATE_PATH, {'total_pollution': 0, 'processed_hashes': {}, 'records': [], 'pet_pool': {}})
        self.state.setdefault('pet_pool', {})
        self.session_hits = 0
        self.refresh_stats()
        self.bridge.log.emit('已重置统计')

    def open_report(self):
        subprocess.Popen(['explorer', str(tracker.REPORT_PATH)])

    def open_species_template_dir(self):
        p = Path((self.cfg.get('species_template_mode', {}) or {}).get('template_dir', str(tracker.SPECIES_TEMPLATE_DIR)))
        p.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(['explorer', str(p)])

    def toggle_topmost(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(enabled))
        self.show()
        self.raise_()
        self.activateWindow()
        if self.floating_orb is not None:
            self.floating_orb.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(enabled))
            self.floating_orb.show()
            self.floating_orb.raise_()
            self.floating_orb.activateWindow()
            self.floating_orb.set_topmost_enabled(bool(enabled))
        self.topmost_pill.setText('置顶开启' if enabled else '置顶关闭')
        self.bridge.log.emit(f"置顶 {'开启' if enabled else '关闭'}")

    def capture_species_template(self):
        if tracker.mss is None:
            QMessageBox.critical(self, '缺少依赖', '需要 mss 才能截取模板。')
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            QMessageBox.critical(self, '截图失败', '未找到可用屏幕。')
            return
        geom = screen.geometry()
        try:
            with tracker.mss.mss() as sct:
                shot = np.array(
                    sct.grab(
                        {
                            'left': geom.left(),
                            'top': geom.top(),
                            'width': geom.width(),
                            'height': geom.height(),
                        }
                    )
                )
            rgba = cv2.cvtColor(shot, cv2.COLOR_BGRA2RGBA)
            image = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QImage.Format.Format_RGBA8888).copy()
            pixmap = QPixmap.fromImage(image)
        except Exception as exc:
            QMessageBox.critical(self, '截图失败', str(exc))
            return
        self.bridge.log.emit('进入模板截图模式，按 Esc 可取消')
        self.hide()
        if self.floating_orb is not None:
            self.floating_orb.hide()
        self.overlay = CaptureOverlay(pixmap)
        self.overlay.setGeometry(geom)
        self.overlay.captured.connect(self._save_template)
        self.overlay.cancelled.connect(self._capture_cancelled)
        self.overlay.show()
        self.overlay.activateWindow()

    def _capture_cancelled(self):
        if self.overlay is not None:
            self.overlay.deleteLater()
            self.overlay = None
        self.tray = None
        self.tray_menu = None
        self.hotkey_filter = None
        self.hotkey_registered = False
        self._quitting = False
        self.show()
        self.raise_()
        self.activateWindow()
        if self.floating_orb is not None:
            self.floating_orb.show()
            self.floating_orb.raise_()
        self.bridge.log.emit('已取消模板截取')

    def _save_template(self, rect):
        if self.overlay is not None:
            self.overlay.deleteLater()
            self.overlay = None
        self.tray = None
        self.tray_menu = None
        self.hotkey_filter = None
        self.hotkey_registered = False
        self._quitting = False
        self.show()
        self.raise_()
        self.activateWindow()
        if self.floating_orb is not None:
            self.floating_orb.show()
            self.floating_orb.raise_()
        if rect.width() < 8 or rect.height() < 8:
            self.bridge.log.emit('模板截取区域过小，已取消')
            return
        name, ok = QInputDialog.getText(self, '模板命名', '输入精灵名：')
        if not ok or not name.strip():
            self.bridge.log.emit('未输入精灵名，模板未保存')
            return
        safe_name = re.sub(r'[\\/:*?"<>|]+', '_', name.strip())
        out_dir = Path((self.cfg.get('species_template_mode', {}) or {}).get('template_dir', str(tracker.SPECIES_TEMPLATE_DIR)))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f'{safe_name}.png'
        try:
            with tracker.mss.mss() as sct:
                shot = np.array(sct.grab({'left': rect.left(), 'top': rect.top(), 'width': rect.width(), 'height': rect.height()}))
            img = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
            if not tracker.write_image(out_path, img):
                raise RuntimeError('图片写入失败')
            self._load_species_templates()
            self.bridge.log.emit(f'模板已保存: {safe_name} -> {out_path.name}')
        except Exception as exc:
            QMessageBox.critical(self, '保存模板失败', str(exc))


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = QtTrackerWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()






