import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QRadialGradient
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
    QMessageBox,
    QPushButton,
    QRubberBand,
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


class QtTrackerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        tracker.init_files()
        self.cfg = tracker.merge_defaults(tracker.load_json(tracker.CONFIG_PATH, tracker.default_config()), tracker.default_config())
        self.state = tracker.load_json(tracker.STATE_PATH, {'total_pollution': 0, 'processed_hashes': {}, 'records': [], 'pet_pool': {}})
        self.state.setdefault('pet_pool', {})
        self.species_templates = []
        self.running = False
        self.stop_event = threading.Event()
        self.worker = None
        self.drag_pos = None
        self.logs = []
        self.overlay = None
        self.bridge = Bridge()
        self.bridge.log.connect(self._append_log)
        self.bridge.status.connect(self._set_status)
        self.bridge.stats.connect(self.refresh_stats)
        self.bridge.error.connect(lambda t, m: QMessageBox.critical(self, t, m))
        self._load_species_templates()

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

    def refresh_stats(self):
        total = str(self.state.get('total_pollution', 0))
        pool = self.state.get('pet_pool', {})
        recs = self.state.get('records', [])
        latest = recs[-1].get('pet_name') if recs else '-'
        self.total_value.setText(total)
        self.species_value.setText(str(len(pool)))
        self.latest_value.setText(latest or '-')
        self.orb.set_value(total)
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
        self.stop_event.set()
        if self.overlay is not None:
            self.overlay.close()
            self.overlay.deleteLater()
            self.overlay = None
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

    def save_settings(self):
        tracker.save_json(tracker.CONFIG_PATH, self.cfg)
        self._load_species_templates()
        self.bridge.log.emit(f"设置已保存：dir={self.cfg.get('watch_dir')}, interval={self.cfg.get('poll_interval_sec')}s")
        return True

    def _match_species_template(self, frame_bgr):
        best = None
        best_score = -1.0
        base_cfg = dict(self.cfg.get('icon_mode', {}))
        base_cfg['use_template'] = True
        for item in self.species_templates:
            hit, score, ratio, reason, _bbox = tracker.detect_purple_icon_in_frame_with_bbox(frame_bgr, base_cfg, item['image'])
            if hit and score > best_score:
                best_score = score
                best = {'name': item['name'], 'score': score, 'ratio': ratio, 'reason': reason}
        return best

    @staticmethod
    def _crop_search_region(frame_bgr, screen_cfg):
        h, w = frame_bgr.shape[:2]
        region_cfg = screen_cfg.get('search_region', {}) or {}
        x_ratio = float(region_cfg.get('x_ratio', 0.0))
        y_ratio = float(region_cfg.get('y_ratio', 0.0))
        w_ratio = float(region_cfg.get('w_ratio', 0.48))
        h_ratio = float(region_cfg.get('h_ratio', 0.36))
        x1 = max(0, min(int(w * x_ratio), w - 1))
        y1 = max(0, min(int(h * y_ratio), h - 1))
        x2 = max(x1 + 1, min(int(w * (x_ratio + w_ratio)), w))
        y2 = max(y1 + 1, min(int(h * (y_ratio + h_ratio)), h))
        return frame_bgr[y1:y2, x1:x2], (x1, y1)

    def _realtime_loop(self):
        try:
            tracker.require_screen_tools()
            screen_cfg = self.cfg.get('screen_mode', {})
            icon_cfg = dict(self.cfg.get('icon_mode', {}))
            icon_cfg['use_template'] = True
            self._load_species_templates()
            if not self.species_templates:
                raise RuntimeError('未找到精灵模板。请先截取模板。')
            self.bridge.log.emit(f'实时识别模式：模板库匹配，共加载 {len(self.species_templates)} 个模板')
            interval = max(float(screen_cfg.get('capture_interval_sec', 0.35)), 0.45)
            min_gap = float(screen_cfg.get('min_trigger_gap_sec', 1.2))
            rearm_absent_sec = float(screen_cfg.get('rearm_absent_sec', 3.0))
            icon_value = int(icon_cfg.get('icon_pollution_value', 1))
            window_hint = str(screen_cfg.get('window_title_contains', '') or '')
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
                    search_bgr, _ = self._crop_search_region(frame_bgr, screen_cfg)
                    match = self._match_species_template(search_bgr)
                    now = time.time()
                    if match and (now - last_trigger_ts >= min_gap):
                        absent_since_ts = None
                        if not battle_locked:
                            pet_name = match['name']
                            last_trigger_ts = now
                            battle_locked = True
                            self.state['total_pollution'] = int(self.state.get('total_pollution', 0)) + icon_value
                            pool = self.state.setdefault('pet_pool', {})
                            item = pool.setdefault(pet_name, {'count': 0, 'pollution': 0})
                            item['count'] += 1
                            item['pollution'] += icon_value
                            self.state.setdefault('records', []).append({'time': int(now), 'pet_name': pet_name})
                            tracker.save_json(tracker.STATE_PATH, self.state)
                            self.bridge.log.emit(f"实时触发 +{icon_value} | 精灵={pet_name} | score={match['score']:.3f} purple={match['ratio']:.3f}")
                            self.bridge.stats.emit()
                    elif not match:
                        if absent_since_ts is None:
                            absent_since_ts = now
                        elif battle_locked and now - absent_since_ts >= rearm_absent_sec:
                            battle_locked = False
                    if now - last_info_ts >= 2.0:
                        self.bridge.log.emit(f"实时状态 hit=True pet={match['name']} score={match['score']:.3f}" if match else '实时状态 hit=False')
                        last_info_ts = now
                    time.sleep(interval)
        except Exception as exc:
            self.bridge.error.emit('实时识别异常', str(exc))
        finally:
            self.running = False
            self.bridge.status.emit('待机', '#8C98A7')

    def start_realtime(self):
        if self.running:
            self.bridge.log.emit('已有模式在运行，请先停止')
            return
        self.save_settings()
        self.stop_event.clear()
        self.running = True
        self.bridge.status.emit('实时识别中', '#8DE0FF')
        self.worker = threading.Thread(target=self._realtime_loop, daemon=True)
        self.worker.start()
        self.bridge.log.emit('开始实时识别')

    def stop_watch(self):
        if not self.running:
            self.bridge.log.emit('当前未运行')
            return
        self.stop_event.set()
        self.running = False
        tracker.save_json(tracker.STATE_PATH, self.state)
        self.bridge.status.emit('待机', '#8C98A7')
        self.bridge.log.emit('已停止实时识别')

    def reset_stats(self):
        if QMessageBox.question(self, '确认', '确定要重置统计吗？') != QMessageBox.StandardButton.Yes:
            return
        tracker.command_reset()
        self.state = tracker.load_json(tracker.STATE_PATH, {'total_pollution': 0, 'processed_hashes': {}, 'records': [], 'pet_pool': {}})
        self.state.setdefault('pet_pool', {})
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
        self.show()
        self.raise_()
        self.activateWindow()
        self.bridge.log.emit('已取消模板截取')

    def _save_template(self, rect):
        if self.overlay is not None:
            self.overlay.deleteLater()
            self.overlay = None
        self.show()
        self.raise_()
        self.activateWindow()
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
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
