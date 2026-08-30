"""
media_backend.py
Media Backend 基类
与具体数据源无关的公共逻辑：Qt 属性、专辑图处理、主色提取与进度插值。

数据源子类（SMTC / MPRIS）只需：
- 在自己的 _start_source() 里接入数据源事件；
- 通过 _mediaUpdated / _timelineUpdated / _playbackUpdated 排队信号
  （跨线程）或直接调用 _apply_*（同一线程）把状态应用到主线程；
- 按需重写 _resync() 做兜底全量同步。

更新策略：
- 数据源事件驱动即时更新；
- 主线程 250ms 插值刷新播放进度，进度平滑移动不依赖轮询；
- 5s 兜底全量同步，纠正可能的漂移或漏掉的事件。
"""

import base64
import time

from loguru import logger
from PySide6.QtCore import QBuffer, QIODevice, QObject, Property, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath

# 专辑图输出尺寸与烘焙圆角（256px + 56px 圆角 ≈ 显示 36px 时视觉半径 8px，符合 M3 小组件观感）
_ART_SIZE = 256
_ART_RADIUS = 56

_TICK_MS = 250        # 进度插值刷新间隔
_RESYNC_MS = 5000     # 兜底同步间隔

# SMTC PlaybackStatus.Playing；MPRIS 的 "Playing" 也映射到 4
_STATUS_PLAYING = 4


class MediaBackend(QObject):
    """向 QML 提供媒体信息的后端对象基类。"""

    # 属性变化信号
    titleChanged = Signal()
    artistChanged = Signal()
    artChanged = Signal()
    progressChanged = Signal()
    playingChanged = Signal()
    accentColorChanged = Signal()
    accentColor2Changed = Signal()

    # 换歌信号（title, artist）：供歌词推送等模块按歌曲触发
    songChanged = Signal(str, str)

    # 内部信号：数据源线程 emit，经排队连接在主线程应用
    # 参数：title, artist, art(data URL), position_ms, duration_ms, accent1, accent2
    _mediaUpdated = Signal(str, str, str, int, int, str, str)
    _timelineUpdated = Signal(int, int)      # position_ms, duration_ms
    _playbackUpdated = Signal(int, float)    # status, rate

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._artist = ""
        self._art = ""
        self._progress = 0.0
        self._position_ms = 0
        self._duration_ms = 0
        self._accent_color = "#9AA0A6"
        self._accent_color2 = "#9AA0A6"
        self._tick_timer = None
        self._resync_timer = None
        # 进度插值基准
        self._playing = False
        self._rate = 1.0
        self._pos_stamp = 0.0
        # 专辑图与主色缓存（数据源线程与主线程共享；引用替换是原子的）
        self._last_art_hash = None
        self._last_art_url = ""
        self._last_palette = ("#9AA0A6", "#9AA0A6")

        self._mediaUpdated.connect(self._apply_update)
        self._timelineUpdated.connect(self._apply_timeline)
        self._playbackUpdated.connect(self._apply_playback)

    # ---- Qt 属性 ----

    @Property(str, notify=titleChanged)
    def title(self):
        return self._title

    @Property(str, notify=artistChanged)
    def artist(self):
        return self._artist

    @Property(str, notify=artChanged)
    def art(self):
        """专辑图（PNG data URL，无图时为空字符串）。"""
        return self._art

    @Property(float, notify=progressChanged)
    def progress(self):
        if self._duration_ms > 0:
            return max(0.0, min(1.0, self._current_position_ms() / self._duration_ms))
        return 0.0

    @Property(str, notify=progressChanged)
    def positionText(self):
        """当前播放位置（M:SS 格式，含插值）。"""
        return self._format_time(self._current_position_ms())

    @Property(str, notify=progressChanged)
    def durationText(self):
        """总时长（M:SS 格式）。"""
        return self._format_time(self._duration_ms)

    @Property(str, notify=accentColorChanged)
    def accentColor(self):
        """从专辑图提取的主色调（hex 字符串）。"""
        return self._accent_color

    @Property(bool, notify=playingChanged)
    def isPlaying(self):
        return self._playing

    @Property(str, notify=accentColor2Changed)
    def accentColor2(self):
        """从专辑图提取的第二主色（hex 字符串），用于渐变另一端。"""
        return self._accent_color2

    @staticmethod
    def _format_time(ms):
        if ms <= 0:
            return "0:00"
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    # ---- 供插件内其他模块使用的普通访问器（非 Qt 属性） ----

    def current_position_ms(self):
        """当前播放位置（含播放中插值，毫秒）。"""
        return self._current_position_ms()

    @property
    def duration_ms(self):
        """当前曲目总时长（毫秒，未知为 0）。"""
        return self._duration_ms

    # ---- 启动框架 ----

    def start(self):
        """启动进度插值定时器并接入数据源（子类实现 _start_source）。"""
        if self._tick_timer is not None:
            return
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(_TICK_MS)

        self._resync_timer = QTimer(self)
        self._resync_timer.timeout.connect(self._resync)
        self._resync_timer.start(_RESYNC_MS)
        logger.info(f"MediaBackend: started (tick={_TICK_MS}ms, resync={_RESYNC_MS}ms)")
        self._start_source()

    def _start_source(self):
        """数据源接入钩子（SMTC / MPRIS 分别实现）。"""

    def _resync(self):
        """兜底同步钩子：子类按数据源实现全量拉取。"""

    # ---- 主线程：状态应用与进度插值 ----

    def _on_tick(self):
        if self._playing:
            self.progressChanged.emit()

    def _current_position_ms(self):
        if not self._playing:
            return self._position_ms
        delta = (time.monotonic() - self._pos_stamp) * 1000.0 * self._rate
        pos = self._position_ms + delta
        if self._duration_ms > 0:
            pos = min(pos, float(self._duration_ms))
        return int(pos)

    def _emit_progress(self):
        if self._duration_ms > 0:
            self._progress = max(0.0, min(1.0, self._current_position_ms() / self._duration_ms))
        else:
            self._progress = 0.0
        self.progressChanged.emit()

    def _apply_update(self, title, artist, art, position_ms, duration_ms, accent1, accent2):
        song_changed = title != self._title or artist != self._artist
        if title != self._title:
            self._title = title
            self.titleChanged.emit()
        if artist != self._artist:
            self._artist = artist
            self.artistChanged.emit()
        if art != self._art:
            self._art = art
            self.artChanged.emit()
        if song_changed:
            self.songChanged.emit(title, artist)

        self._position_ms = max(0, position_ms)
        self._duration_ms = max(0, duration_ms)

        if accent1 != self._accent_color:
            self._accent_color = accent1
            self.accentColorChanged.emit()
        if accent2 != self._accent_color2:
            self._accent_color2 = accent2
            self.accentColor2Changed.emit()
        self._emit_progress()

    def _apply_timeline(self, position_ms, duration_ms):
        self._position_ms = max(0, position_ms)
        self._duration_ms = max(0, duration_ms)
        self._pos_stamp = time.monotonic()
        self._emit_progress()

    def _apply_playback(self, status, rate):
        # 先按旧状态结算当前位置，避免重置时间基准导致进度回跳
        self._position_ms = self._current_position_ms()
        was_playing = self._playing
        self._playing = (status == _STATUS_PLAYING)
        self._rate = rate if rate > 0 else 1.0
        self._pos_stamp = time.monotonic()
        if was_playing != self._playing:
            self.playingChanged.emit()
        self._emit_progress()

    # ---- 专辑图处理 ----

    def process_art_bytes(self, raw: bytes) -> str:
        """内容未变化时复用上次的 data URL，否则居中裁方 → 缩放 → 烘焙圆角 → PNG data URL。"""
        key = self._art_hash(raw)
        if key == self._last_art_hash and self._last_art_url:
            return self._last_art_url
        url = self._rounded_png_data_url(raw)
        if url:
            self._last_art_hash = key
            self._last_art_url = url
        return url

    @staticmethod
    def _art_hash(raw: bytes) -> str:
        import hashlib
        return hashlib.md5(raw).hexdigest()

    @staticmethod
    def _rounded_png_data_url(raw: bytes) -> str:
        """居中裁方 → 缩放 → 烘焙圆角 → PNG data URL。"""
        img = QImage.fromData(raw)
        if img.isNull():
            return ""
        if img.width() != img.height():
            side = min(img.width(), img.height())
            img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
        img = img.scaled(
            _ART_SIZE, _ART_SIZE,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # 圆角直接烘焙进位图，QML 侧无需依赖图形效果模块
        rounded = QImage(_ART_SIZE, _ART_SIZE, QImage.Format.Format_ARGB32)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, _ART_SIZE, _ART_SIZE), _ART_RADIUS, _ART_RADIUS)
        painter.setClipPath(path)
        painter.drawImage(0, 0, img)
        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        if not rounded.save(buf, "PNG"):
            return ""
        return "data:image/png;base64," + base64.b64encode(bytes(buf.data())).decode("ascii")

    # ---- 主色调提取 ----

    def _extract_palette(self, data_url: str):
        """从专辑图提取渐变两端主色，返回 (primary, secondary) hex。"""
        try:
            if not data_url.startswith("data:image/"):
                return self._last_palette
            _, b64data = data_url.split(",", 1)
            raw = base64.b64decode(b64data)
            img = QImage.fromData(raw)
            if img.isNull():
                return self._last_palette

            small = img.scaled(16, 16, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            color_counts = {}
            for y in range(small.height()):
                for x in range(small.width()):
                    c = small.pixelColor(x, y)
                    if c.alpha() < 128:
                        continue
                    # 量化到 32 级，减少颜色数量
                    key = (c.red() // 32 * 32, c.green() // 32 * 32, c.blue() // 32 * 32)
                    color_counts[key] = color_counts.get(key, 0) + 1
            if not color_counts:
                return self._last_palette

            scored = sorted(
                color_counts.items(),
                key=lambda kv: kv[1] * self._color_weight(kv[0]),
                reverse=True,
            )
            primary, primary_count = scored[0]
            secondary = None
            min_count = max(2, primary_count * 0.15)
            for key, count in scored[1:]:
                if count < min_count:
                    continue
                if self._color_distance(key, primary) >= 96:
                    secondary = key
                    break
            if secondary is None:
                secondary = self._derive_variant(primary)

            palette = (self._to_hex(primary), self._to_hex(secondary))
            self._last_palette = palette
            return palette
        except Exception as e:
            logger.debug(f"MediaBackend: extract palette failed: {e}")
            return self._last_palette

    @staticmethod
    def _color_weight(rgb):
        """给颜色一个权重：避免太暗或太亮的颜色被选中。"""
        r, g, b = rgb
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        if brightness < 40 or brightness > 220:
            return 0.1
        return 1.0

    @staticmethod
    def _color_distance(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5

    @staticmethod
    def _derive_variant(rgb):
        """没有足够分量的第二主色时，从主色派生一个明度反差色。"""
        r, g, b = rgb
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        factor = 0.55 if brightness > 128 else 1.55
        return (
            max(0, min(255, int(r * factor))),
            max(0, min(255, int(g * factor))),
            max(0, min(255, int(b * factor))),
        )

    @staticmethod
    def _to_hex(rgb):
        r, g, b = rgb
        return f"#{r:02X}{g:02X}{b:02X}"
