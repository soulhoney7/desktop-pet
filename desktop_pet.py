# -*- coding: utf-8 -*-
"""
데스크탑 펫
- 사진을 넣으면 배경을 자동으로 지우고 바탕화면을 돌아다니는 펫으로 만들어 줍니다.
- 움직임/행동 로직은 pet_brain.py, 배경 제거는 bgremove.py
"""
import json
import math
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QPoint, QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, 
    QLabel, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider,
    QSystemTrayIcon, QTextBrowser, QVBoxLayout, QWidget,
)

import random

from help_text import HELP_HTML
import winplat
from pet_brain import PetBrain

APP_NAME = "데스크탑 펫"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "DesktopPet"
PET_DIR = DATA_DIR / "pets"
SETTINGS_FILE = DATA_DIR / "settings.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".gif", ".tif", ".tiff",
              ".heic", ".heif", ".avif", ".ico"}

BASE_HEIGHT = 110      # 크기 100%일 때 펫 높이(px)
TICK_MS = 30
EMO_SPACE = 56         # 펫 머리 위 이모티콘 공간
PINK = "#f06292"


# ──────────────────────────── 설정 저장 ────────────────────────────
class Settings:
    def __init__(self):
        self.data = {"global_scale": 100, "pets": {}}
        if SETTINGS_FILE.exists():
            try:
                self.data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def pet(self, name):
        return self.data["pets"].setdefault(name, {"enabled": True, "scale": 100})


# ──────────────────────────── 배경 제거 작업 ────────────────────────────
class BackgroundRemover(QThread):
    progress = Signal(str)
    finished_one = Signal(str)
    failed = Signal(str, str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        import bgremove
        for i, path in enumerate(self.paths, 1):
            path = Path(path)
            try:
                self.progress.emit(f"{path.name} 배경 지우는 중… ({i}/{len(self.paths)})")
                img = bgremove.make_pet_image(path, self.progress.emit)
                PET_DIR.mkdir(parents=True, exist_ok=True)
                stem = "".join(c for c in path.stem if c not in '\\/:*?"<>|')[:30] or "pet"
                name, n = stem, 2
                while (PET_DIR / f"{name}.png").exists():
                    name, n = f"{stem}_{n}", n + 1
                img.save(PET_DIR / f"{name}.png")
                self.finished_one.emit(name)
            except Exception as e:
                msg = str(e)
                if "urlopen" in msg or "Errno" in msg or "timed out" in msg:
                    msg = "배경 제거 모델을 내려받지 못했어요. 인터넷 연결을 확인해 주세요.\n\n" + msg
                self.failed.emit(path.name, msg)


# ──────────────────────────── 펫 창 ────────────────────────────
def screen_area(x, y):
    screen = QGuiApplication.screenAt(QPoint(int(x), int(y))) or QGuiApplication.primaryScreen()
    g = screen.availableGeometry()
    return (g.x(), g.y(), g.x() + g.width(), g.y() + g.height())


class PetWindow(QWidget):
    def __init__(self, name, app_ref):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.name = name
        self.app_ref = app_ref
        self.source = QPixmap(str(PET_DIR / f"{name}.png"))
        self.pix = self.source
        self.drag_offset = None
        self.drag_hist = []
        self.pw = self.ph = 10

        prim = QGuiApplication.primaryScreen().availableGeometry()
        self.update_scale(first=True)
        self.brain = PetBrain(self.pw, self.ph, (prim.x(), prim.y(), prim.x() + prim.width(),
                                                  prim.y() + prim.height()))
        self.place()

    def update_scale(self, first=False):
        s = self.app_ref.settings
        scale = s.pet(self.name)["scale"] / 100 * s.data["global_scale"] / 100
        h = max(24, int(BASE_HEIGHT * scale))
        ratio = self.source.width() / max(1, self.source.height())
        w = max(12, int(h * ratio))
        if w > h * 1.6:                      # 아주 가로로 긴 사진은 너비 기준으로
            w = int(h * 1.6)
            h = int(w / ratio)
        dpr = self.devicePixelRatioF()
        pm = self.source.scaled(QSize(int(w * dpr), int(h * dpr)), Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.pix, self.pw, self.ph = pm, w, h
        side = int(math.hypot(w, h) * 1.25) + 16
        self.setFixedSize(side, side + EMO_SPACE)
        if not first:
            self.brain.set_size(w, h)

    def visual_center(self):
        b = self.brain
        return b.cx, b.cy + b.hop_y - b.bob

    def place(self):
        x, y = self.visual_center()
        self.move(int(x - self.width() / 2), int(y - EMO_SPACE - (self.height() - EMO_SPACE) / 2))

    def tick(self, now, mouse, others, plats):
        b = self.brain
        area = screen_area(b.cx, b.cy)
        b.update(now, area, mouse, others, plats)
        self.place()
        self.update()

    # ── 그리기 ──
    def paintEvent(self, _):
        b = self.brain
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing | QPainter.TextAntialiasing)
        cx = self.width() / 2
        cy = EMO_SPACE + (self.height() - EMO_SPACE) / 2
        w, h = self.pw, self.ph

        p.save()
        p.translate(cx, cy)
        p.rotate(b.angle)
        sx = 1 + 0.2 * b.squash + 0.6 * b.flat_now
        sy = 1 - 0.2 * b.squash - b.flat_now
        p.translate(0, h / 2)               # 발끝 기준으로 찌그러지게
        p.scale(sx * b.facing, sy)
        p.translate(0, -h / 2)
        p.drawPixmap(QRectF(-w / 2, -h / 2, w, h), self.pix, QRectF(self.pix.rect()))
        p.restore()

        # 머리 위 이모티콘
        now = b.now
        head_y = cy - h / 2 - 2 if abs(b.angle) < 45 else cy - w / 2 - 2
        for text, t0, dur, dx in b.emotes:
            k = (now - t0) / dur
            if not 0 <= k <= 1:
                continue
            alpha = int(255 * (1 - max(0, k - 0.6) / 0.4))
            y = head_y - 6 - k * 34
            x = cx + dx + (math.sin(k * 9) * 4 if text in ("z", "♪") else 0)
            size = 15 if text in ("z",) else 19
            if text == "z":
                size = int(12 + k * 8)
            font = QFont("Segoe UI Emoji" if text == "💦" else "Malgun Gothic", size, QFont.Bold)
            p.setFont(font)
            color = {"♥": QColor(240, 80, 120), "♪": QColor(90, 120, 230), "★": QColor(250, 190, 30),
                     "!": QColor(235, 70, 60), "?": QColor(80, 140, 230), "z": QColor(120, 120, 160)}.get(
                text, QColor(80, 160, 230))
            # 흰 테두리
            p.setPen(QColor(255, 255, 255, alpha))
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(QPointF(x - size / 2 + ox, y + oy), text)
            color.setAlpha(alpha)
            p.setPen(color)
            p.drawText(QPointF(x - size / 2, y), text)
        p.end()

    # ── 마우스 ──
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            g = e.globalPosition()
            self.brain.start_drag()
            self.drag_offset = QPointF(g.x() - self.brain.cx, g.y() - self.brain.cy)
            self.drag_hist = [(time.time(), g)]
            self.press_pos = g

    def mouseMoveEvent(self, e):
        g = e.globalPosition()
        if self.drag_offset is not None:
            last = self.drag_hist[-1][1]
            self.drag_hist = (self.drag_hist + [(time.time(), g)])[-6:]
            self.brain.drag_to(g.x() - self.drag_offset.x(), g.y() - self.drag_offset.y(), g.x() - last.x())
            self.place()
        elif not e.buttons():
            self.brain.stroke()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag_offset is not None:
            (t0, p0), (t1, p1) = self.drag_hist[0], self.drag_hist[-1]
            if time.time() - t1 > 0.12:        # 멈췄다가 놓으면 그냥 떨어뜨림
                vx = vy = 0.0
            else:
                frames = max((t1 - t0) * 1000 / TICK_MS, 0.5)
                vx = max(-40, min(40, (p1.x() - p0.x()) / frames))
                vy = max(-40, min(40, (p1.y() - p0.y()) / frames))
            self.drag_offset = None
            self.brain.throw(vx, vy)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            b = self.brain
            self.drag_offset = None
            area = screen_area(b.cx, b.cy)
            if b.cy >= b.ground(area) - 2:
                b.state = "idle"
            b.poke()

    def contextMenuEvent(self, e):
        b = self.brain
        menu = QMenu(self)
        free = b.state not in ("air", "drag", "climb", "hang")

        def act(fn):
            return lambda: fn() if b.state not in ("air", "drag", "climb", "hang") else None

        def dance():
            b.angle = 0
            b.set_state("dance", 4, 6)
            b.emote("note")

        def sleep():
            b.angle = 0
            b.flat = 0.22
            b.set_state("sleep", 10, 20)
            b.emote("z", 1.8)

        def climb():
            b.angle = 0
            b.speed = 3
            b.set_state("to_wall", 15, 15)

        for text, fn in (("점프!", b.jump), ("공중제비", lambda: b.jump(flip=True)),
                         ("춤추기 ♪", dance), ("재우기 z", sleep), ("벽 타기", climb)):
            a = menu.addAction(text, act(fn))
            a.setEnabled(free)
        menu.addSeparator()
        menu.addAction("이 펫 숨기기", lambda: self.app_ref.set_enabled(self.name, False))
        menu.addAction("설정 열기", self.app_ref.show_settings)
        menu.addAction("사용법", self.app_ref.show_help)
        menu.exec(e.globalPos())


# ──────────────────────────── 설정창 ────────────────────────────
class PetCard(QFrame):
    def __init__(self, name, app_ref):
        super().__init__()
        self.setObjectName("card")
        self.setFixedSize(150, 172)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.addStretch()
        delete = QPushButton("×")
        delete.setObjectName("del")
        delete.setFixedSize(22, 22)
        delete.setToolTip("펫 삭제")
        delete.clicked.connect(lambda: app_ref.delete_pet(name))
        top.addWidget(delete)
        lay.addLayout(top)

        thumb = QLabel()
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setPixmap(QPixmap(str(PET_DIR / f"{name}.png")).scaled(
            QSize(84, 72), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(thumb, 1)

        cfg = app_ref.settings.pet(name)
        self.check = QCheckBox(name if len(name) <= 10 else name[:9] + "…")
        self.check.setToolTip(name)
        self.check.setChecked(cfg["enabled"])
        self.check.toggled.connect(lambda on: app_ref.set_enabled(name, on))
        lay.addWidget(self.check, 0, Qt.AlignCenter)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(40, 250)
        slider.setValue(cfg["scale"])
        slider.setToolTip("이 펫 크기")
        slider.valueChanged.connect(lambda v: app_ref.set_scale(name, v))
        lay.addWidget(slider)
        self.refresh_style()

    def refresh_style(self):
        self.setProperty("on", self.check.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)


class SettingsWindow(QWidget):
    def __init__(self, app_ref):
        super().__init__()
        self.app_ref = app_ref
        self.cards = {}
        self._cols = 0
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(700, 640)
        self.setStyleSheet(f"""
            QWidget {{ font-family: 'Malgun Gothic', sans-serif; font-size: 13px; color: #333; }}
            SettingsWindow, QScrollArea, #grid {{ background: #ffffff; }}
            #card {{ background: #f4f4f6; border-radius: 14px; }}
            #card[on="true"] {{ background: #fde4ec; }}
            QPushButton {{ background: #efeff2; border: none; border-radius: 8px; padding: 6px 12px; }}
            QPushButton:hover {{ background: #e3e3e8; }}
            #add {{ background: {PINK}; color: white; font-weight: bold; padding: 9px 16px; }}
            #add:hover {{ background: #e04f82; }}
            #del {{ background: transparent; color: #aaa; font-size: 15px; padding: 0; }}
            #del:hover {{ color: #e53935; }}
            QSlider::groove:horizontal {{ height: 4px; background: #ddd; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {PINK}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: white; border: 1px solid #ccc; width: 14px; margin: -6px 0; border-radius: 7px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; }}
            QCheckBox::indicator:checked {{ background: {PINK}; border: 1px solid {PINK}; border-radius: 3px; }}
            QCheckBox::indicator:unchecked {{ background: white; border: 1px solid #bbb; border-radius: 3px; }}
            #hint {{ color: #999; font-size: 12px; }}
            #status {{ color: {PINK}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)

        top = QHBoxLayout()
        add = QPushButton("+ 사진 추가")
        add.setObjectName("add")
        add.clicked.connect(self.pick_files)
        top.addWidget(add)
        self.status = QLabel("")
        self.status.setObjectName("status")
        top.addWidget(self.status, 1)
        help_btn = QPushButton("? 사용법")
        help_btn.clicked.connect(app_ref.show_help)
        top.addWidget(help_btn)
        for text, on in (("모두 켜기", True), ("모두 끄기", False)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, on=on: app_ref.set_all(on))
            top.addWidget(btn)
        root.addLayout(top)

        self.empty = QLabel("아직 펫이 없어요.\n\n사진을 이 창에 끌어다 놓거나 (여러 장·폴더도 OK)\n'+ 사진 추가'를 누르거나, 복사한 그림을 Ctrl+V 하세요.\n배경은 자동으로 지워져요 ✨\n\nPNG · JPG · WEBP · GIF · BMP · TIFF · HEIC(아이폰) · AVIF")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("hint")
        self.empty.setStyleSheet("font-size: 16px;")

        self.grid_host = QWidget()
        self.grid_host.setObjectName("grid")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.empty, 1)
        root.addWidget(self.scroll, 1)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("전체 크기"))
        self.global_slider = QSlider(Qt.Horizontal)
        self.global_slider.setRange(40, 250)
        self.global_slider.setValue(app_ref.settings.data["global_scale"])
        self.global_slider.valueChanged.connect(app_ref.set_global_scale)
        size_row.addWidget(self.global_slider, 1)
        reset = QPushButton("기본값")
        reset.clicked.connect(lambda: self.global_slider.setValue(100))
        size_row.addWidget(reset)
        size_row.addSpacing(12)
        self.win_check = QCheckBox("열린 창 위에서 놀기")
        self.win_check.setToolTip("새 창이 열리면 펫이 뛰어올라가고, 창을 옮기면 같이 타고 다녀요")
        self.win_check.setChecked(app_ref.settings.data.get("window_play", True))
        self.win_check.toggled.connect(app_ref.set_window_play)
        size_row.addWidget(self.win_check)
        root.addLayout(size_row)

        bottom = QHBoxLayout()
        hint = QLabel("창을 닫아도 펫은 계속 놀아요. 작업표시줄 오른쪽 발바닥 아이콘이나 펫 우클릭으로 이 창을 다시 열 수 있어요.\n"
                      "펫을 집어 던지거나, 더블클릭(점프)하거나, 마우스로 문질러(쓰다듬기) 보세요.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        bottom.addWidget(hint, 1)
        quit_btn = QPushButton("프로그램 종료")
        quit_btn.clicked.connect(app_ref.quit)
        bottom.addWidget(quit_btn, 0, Qt.AlignBottom)
        root.addLayout(bottom)

    def cols(self):
        return max(1, (self.scroll.viewport().width() - 10) // 160)

    def rebuild(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cards.clear()
        names = self.app_ref.pet_names()
        self._cols = self.cols()
        for i, name in enumerate(names):
            card = PetCard(name, self.app_ref)
            self.cards[name] = card
            self.grid.addWidget(card, i // self._cols, i % self._cols)
        self.empty.setVisible(not names)
        self.scroll.setVisible(bool(names))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._cols and self.cols() != self._cols:
            self.rebuild()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.rebuild)

    def sync_checks(self):
        for name, card in self.cards.items():
            card.check.blockSignals(True)
            card.check.setChecked(self.app_ref.settings.pet(name)["enabled"])
            card.check.blockSignals(False)
            card.refresh_style()

    def pick_files(self):
        pattern = " ".join("*" + e for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "펫으로 만들 사진 고르기 (여러 장 한꺼번에 골라도 돼요)", str(Path.home() / "Pictures"),
            f"이미지 ({pattern});;모든 파일 (*.*)")
        if files:
            self.app_ref.add_images(files)

    def take_images(self, mime):
        """끌어다 놓기 / 붙여넣기 내용에서 이미지 파일 모으기 (폴더면 안의 이미지 전부)"""
        files = []
        for u in mime.urls() if mime.hasUrls() else []:
            p = Path(u.toLocalFile())
            if not u.isLocalFile():
                continue
            if p.is_dir():
                files += sorted(str(f) for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS)
            elif p.suffix.lower() in IMAGE_EXTS:
                files.append(str(p))
        if not files and mime.hasImage():
            # 웹 브라우저에서 끌어온 그림, 캡처 도구로 복사한 그림 등
            img = mime.imageData()
            if img is not None and not img.isNull():
                tmp_dir = DATA_DIR / "tmp"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                path = tmp_dir / time.strftime("붙여넣은그림_%H%M%S.png")
                img.save(str(path))
                files.append(str(path))
        return files

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = self.take_images(e.mimeData())
        if files:
            self.app_ref.add_images(files)
        else:
            self.status.setText("지원하는 이미지 파일이 없어요")

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):          # Ctrl+V로 붙여넣기
            files = self.take_images(QGuiApplication.clipboard().mimeData())
            if files:
                self.app_ref.add_images(files)
            else:
                self.status.setText("클립보드에 그림이 없어요")
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        e.ignore()
        self.hide()


class HelpWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("데스크탑 펫 사용법")
        self.resize(620, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setFrameShape(QFrame.NoFrame)
        view.setStyleSheet("QTextBrowser { background: white; padding: 14px 18px; }")
        view.setHtml(HELP_HTML)
        lay.addWidget(view, 1)
        close = QPushButton("닫기")
        close.setStyleSheet(f"QPushButton {{ background: {PINK}; color: white; font-weight: bold; border: none;"
                            " border-radius: 8px; padding: 8px 28px; }")
        close.clicked.connect(self.hide)
        lay.addWidget(close, 0, Qt.AlignCenter)


# ──────────────────────────── 앱 ────────────────────────────
def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(PINK))
    p.setPen(Qt.NoPen)
    p.drawEllipse(18, 28, 28, 26)
    for cx, cy in [(12, 22), (24, 12), (40, 12), (52, 22)]:
        p.drawEllipse(cx - 7, cy - 7, 14, 14)
    p.end()
    return QIcon(pm)


class PetApp:
    def __init__(self, qapp):
        self.qapp = qapp
        qapp.setQuitOnLastWindowClosed(False)
        PET_DIR.mkdir(parents=True, exist_ok=True)
        self.settings = Settings()
        self.pets = {}
        self.workers = []

        self.icon = make_icon()
        qapp.setWindowIcon(self.icon)
        self.window = SettingsWindow(self)
        self.help = None

        self.tray = QSystemTrayIcon(self.icon)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("설정 열기", self.show_settings)
        menu.addAction("사용법", self.show_help)
        menu.addAction("모두 켜기", lambda: self.set_all(True))
        menu.addAction("모두 끄기", lambda: self.set_all(False))
        menu.addSeparator()
        menu.addAction("종료", self.quit)
        self.tray.setContextMenu(menu)
        self._menu = menu
        self.tray.activated.connect(self.on_tray)
        self.tray.show()

        for name in self.pet_names():
            if self.settings.pet(name)["enabled"]:
                self.spawn(name)
        self.settings.save()

        self.t0 = time.time()
        self.frame = 0
        self.plats = {}
        self.seen_windows = None
        self.new_windows = {}
        self.timer = QTimer()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

        if not self.pets or "--settings" in sys.argv:
            self.show_settings()
        if not self.settings.data.get("help_shown"):
            self.settings.data["help_shown"] = True
            self.settings.save()
            QTimer.singleShot(400, self.show_help)

    def on_tray(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_settings()

    def pet_names(self):
        return sorted(p.stem for p in PET_DIR.glob("*.png"))

    def show_help(self):
        if self.help is None:
            self.help = HelpWindow()
        self.help.show()
        self.help.raise_()
        self.help.activateWindow()

    def show_settings(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def spawn(self, name):
        if name not in self.pets:
            pet = PetWindow(name, self)
            self.pets[name] = pet
            pet.show()

    # ── 열린 창 = 발판 ──
    def to_logical(self, x, y):
        """윈도우 API의 물리 픽셀 → Qt 화면 좌표 (배율 125%, 150% 등 대응)"""
        for s in QGuiApplication.screens():
            g, d = s.geometry(), s.devicePixelRatio()
            if g.x() <= x < g.x() + g.width() * d and g.y() <= y < g.y() + g.height() * d:
                return g.x() + (x - g.x()) / d, g.y() + (y - g.y()) / d
        d = QGuiApplication.primaryScreen().devicePixelRatio()
        return x / d, y / d

    def scan_windows(self, now):
        if not self.settings.data.get("window_play", True):
            self.plats = {}
            return
        try:
            raw = winplat.platforms()
        except Exception:
            raw = {}
        plats = {}
        for hwnd, segs in raw.items():
            for i, (x1, x2, y, wl) in enumerate(segs):
                lx1, ly = self.to_logical(x1, y)
                lx2, _ = self.to_logical(x2, y)
                lwl, _ = self.to_logical(wl, y)
                plats[(hwnd, i)] = (lx1, lx2, ly, lwl)

        # 가림 상태가 바뀌어 구간 번호가 달라져도, 같은 창이면 계속 서 있게
        for pet in self.pets.values():
            b = pet.brain
            if b.on is not None and b.on not in plats:
                hwnd = b.on[0]
                for key, (x1, x2, y, wl) in plats.items():
                    if key[0] == hwnd and x1 - b.w * 0.3 <= b.cx <= x2 + b.w * 0.3:
                        b.on = key
                        break

        # 새로 열린 창 (최소화했다 다시 연 창 포함) → 조금 뒤 펫이 뛰어오름
        hwnds = {k[0] for k in plats}
        if self.seen_windows is not None:
            for h in hwnds - self.seen_windows:
                self.new_windows[h] = now + 0.6       # 창 열리는 애니메이션 끝날 때까지 기다림
        self.seen_windows = hwnds
        for h, at in list(self.new_windows.items()):
            if now < at:
                continue
            del self.new_windows[h]
            keys = [k for k in plats if k[0] == h]
            if not keys:
                continue
            key = max(keys, key=lambda k: plats[k][1] - plats[k][0])
            x1, x2, y, _ = plats[key]
            mid = (x1 + x2) / 2
            jumped = 0
            for pet in sorted(self.pets.values(), key=lambda p: abs(p.brain.cx - mid)):
                if pet.brain.notice_platform(key, plats):
                    jumped += 1
                    if jumped >= 2 or random.random() < 0.6:
                        break
        self.plats = plats

    def set_window_play(self, on):
        self.settings.data["window_play"] = on
        self.settings.save()

    def tick(self):
        now = time.time() - self.t0
        self.frame += 1
        if self.frame % 2 == 0:
            self.scan_windows(now)
        c = QCursor.pos()
        mouse = (c.x(), c.y())
        brains = [p.brain for p in self.pets.values()]
        for pet in list(self.pets.values()):
            pet.tick(now, mouse, brains, self.plats)

    def set_enabled(self, name, on):
        self.settings.pet(name)["enabled"] = on
        self.settings.save()
        if on:
            self.spawn(name)
        elif name in self.pets:
            self.pets.pop(name).close()
        self.window.sync_checks()

    def set_all(self, on):
        for name in self.pet_names():
            self.set_enabled(name, on)

    def set_scale(self, name, value):
        self.settings.pet(name)["scale"] = value
        self.settings.save()
        if name in self.pets:
            self.pets[name].update_scale()

    def set_global_scale(self, value):
        self.settings.data["global_scale"] = value
        self.settings.save()
        for pet in self.pets.values():
            pet.update_scale()

    def delete_pet(self, name):
        if QMessageBox.question(self.window, "펫 삭제", f"'{name}' 펫을 삭제할까요?") != QMessageBox.Yes:
            return
        if name in self.pets:
            self.pets.pop(name).close()
        (PET_DIR / f"{name}.png").unlink(missing_ok=True)
        self.settings.data["pets"].pop(name, None)
        self.settings.save()
        self.window.rebuild()

    def add_images(self, paths):
        worker = BackgroundRemover(paths)
        worker.progress.connect(self.window.status.setText)
        worker.finished_one.connect(self.on_added)
        worker.failed.connect(lambda f, err: QMessageBox.warning(self.window, "추가 실패", f"{f}\n\n{err}"))
        worker.finished.connect(lambda: self.on_worker_done(worker))
        self.workers.append(worker)
        worker.start()

    def on_worker_done(self, worker):
        self.window.status.setText("완료! ✨")
        QTimer.singleShot(3000, lambda: self.window.status.setText(""))
        if worker in self.workers:
            self.workers.remove(worker)

    def on_added(self, name):
        self.settings.pet(name)
        self.settings.save()
        self.spawn(name)
        self.window.rebuild()

    def quit(self):
        self.settings.save()
        self.tray.hide()
        for pet in self.pets.values():
            pet.close()
        self.qapp.quit()


def install_error_log():
    """오류가 나면 %APPDATA%\\DesktopPet\\error.log에 기록 (창 없는 exe라 오류가 안 보이므로)"""
    import traceback

    def hook(etype, value, tb):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / "error.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n"))
                f.write("".join(traceback.format_exception(etype, value, tb)) + "\n")
        except Exception:
            pass
    sys.excepthook = hook


def main():
    install_error_log()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setFont(QFont("Malgun Gothic", 9))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    single = QLockFile(str(DATA_DIR / "running.lock"))
    if not single.tryLock(100):
        QMessageBox.information(None, APP_NAME, "이미 실행 중이에요.\n작업표시줄 오른쪽 발바닥 아이콘을 눌러 보세요.")
        return

    app = PetApp(qapp)
    qapp.exec()
    single.unlock()


if __name__ == "__main__":
    main()
