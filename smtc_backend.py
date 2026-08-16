"""
SMTC Backend
负责从 Windows SMTC (System Media Transport Controls) 获取当前媒体信息，
并通过 Qt 属性暴露给 QML。
"""

import asyncio
import base64
import hashlib
import threading

from loguru import logger
from PySide6.QtCore import QBuffer, QIODevice, QObject, Property, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor

# 专辑图输出尺寸与烘焙圆角（256px + 56px 圆角 ≈ 显示 36px 时视觉半径 8px，符合 M3 小组件观感）
_ART_SIZE = 256
_ART_RADIUS = 56


class SmtcBackend(QObject):
    """向 QML 提供 SMTC 媒体信息的后端对象。"""

    # 属性变化信号
    titleChanged = Signal()
    artistChanged = Signal()
    artChanged = Signal()
    progressChanged = Signal()
    accentColorChanged = Signal()

    # 内部信号：工作线程 emit，经排队连接在主线程执行 _apply_update
    # 参数：title, artist, art(data URL), position_ms, duration_ms, accent_color
    _mediaUpdated = Signal(str, str, str, int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._artist = ""
        self._art = ""
        self._progress = 0.0
        self._position_ms = 0
        self._duration_ms = 0
        self._accent_color = "#9AA0A6"
        self._manager_cls = None
        self._loop = None
        self._thread = None
        self._timer = None
        # 仅在工作线程访问：避免每次轮询重复编码相同的专辑图
        self._last_art_hash = None
        self._last_art_url = ""
        self._last_accent = "#9AA0A6"
        self._mediaUpdated.connect(self._apply_update)

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
        """播放进度（0.0 ~ 1.0）。"""
        return self._progress

    @Property(str, notify=progressChanged)
    def positionText(self):
        """当前播放位置（M:SS 格式）。"""
        return self._format_time(self._position_ms)

    @Property(str, notify=progressChanged)
    def durationText(self):
        """总时长（M:SS 格式）。"""
        return self._format_time(self._duration_ms)

    @Property(str, notify=accentColorChanged)
    def accentColor(self):
        """从专辑图提取的主色调（hex 字符串）。"""
        return self._accent_color

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

    # ---- SMTC 轮询（延迟启动）----

    def start(self):
        """延迟启动 SMTC 轮询，避免在插件加载阶段失败。"""
        if self._timer is not None:
            return

        logger.info("SMTC: start() called, importing winrt...")

        # 延迟导入 winrt
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager,
            )
            self._manager_cls = GlobalSystemMediaTransportControlsSessionManager
            logger.info("SMTC: winrt imported successfully")
        except Exception as e:
            logger.error(f"SMTC: winrt import failed: {e}")
            return

        # 启动 asyncio 事件循环线程
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("SMTC: asyncio loop thread started")

        # 立即执行一次获取
        asyncio.run_coroutine_threadsafe(self._fetch(), self._loop)

        # 定期轮询 SMTC（每 2 秒）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(2000)
        logger.info("SMTC: polling timer started (2s interval)")

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _poll(self):
        if self._manager_cls is None or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._fetch(), self._loop)

    async def _fetch(self):
        try:
            logger.debug("SMTC: fetching media info...")
            manager = await self._manager_cls.request_async()
            session = manager.get_current_session()
            if session is None:
                logger.debug("SMTC: no current session")
                self._mediaUpdated.emit("", "", "", 0, 0, self._last_accent)
                return

            props = await session.try_get_media_properties_async()
            new_title = props.title or ""
            new_artist = props.artist or ""
            new_art = await self._load_art(props)

            # 获取播放进度
            position_ms = 0
            duration_ms = 0
            try:
                ti = await session.get_timeline_properties_async()
                if ti is not None:
                    pos = getattr(ti, "position", None)
                    end = getattr(ti, "end_time", None)
                    if pos is not None:
                        position_ms = int(pos.total_seconds() * 1000)
                    if end is not None:
                        duration_ms = int(end.total_seconds() * 1000)
            except Exception as e:
                logger.debug(f"SMTC: get timeline failed: {e}")

            # 取色
            accent = self._last_accent
            if new_art:
                accent = self._extract_accent(new_art)

            logger.info(f"SMTC: got title={new_title!r}, artist={new_artist!r}, art={bool(new_art)}, pos={position_ms}, dur={duration_ms}")
            self._mediaUpdated.emit(new_title, new_artist, new_art, position_ms, duration_ms, accent)
        except Exception as e:
            logger.error(f"SMTC: fetch failed: {e}")
            self._mediaUpdated.emit("", "", "", 0, 0, self._last_accent)

    async def _load_art(self, props) -> str:
        """读取 SMTC 缩略图并转为圆角 PNG data URL（失败/无图返回空字符串）。"""
        stream = None
        try:
            thumbnail = getattr(props, "thumbnail", None)
            if thumbnail is None:
                return ""
            stream = await thumbnail.open_read_async()
            size = stream.size
            if size <= 0 or size > 20 * 1024 * 1024:
                return ""

            from winrt.windows.storage.streams import DataReader
            reader = DataReader(stream)
            loaded = await reader.load_async(size)
            if loaded <= 0:
                return ""
            raw = bytearray(loaded)
            try:
                # winrt-runtime 3.x：read_bytes 接收可写缓冲区并原地填充，无返回值
                # （传 int 会报 "a bytes-like object is required, not 'int'"）
                reader.read_bytes(raw)
            except TypeError:
                # 旧版 winsdk / pywinrt 2.x：read_bytes(count) -> bytes
                raw = reader.read_bytes(loaded)

            # 内容未变化时复用上次的 data URL，避免每 2 秒重复编码
            key = hashlib.md5(raw).hexdigest()
            if key == self._last_art_hash and self._last_art_url:
                return self._last_art_url

            url = self._rounded_png_data_url(raw)
            if url:
                self._last_art_hash = key
                self._last_art_url = url
            return url
        except Exception as e:
            logger.debug(f"SMTC: load album art failed: {e}")
            return ""
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

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

    def _extract_accent(self, data_url: str) -> str:
        """从专辑图 data URL 中提取主色调（hex 字符串）。"""
        try:
            # 解码 data URL
            if not data_url.startswith("data:image/"):
                return self._last_accent
            header, b64data = data_url.split(",", 1)
            raw = base64.b64decode(b64data)
            img = QImage.fromData(raw)
            if img.isNull():
                return self._last_accent

            # 缩小到 16x16 加速取色
            small = img.scaled(16, 16, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            # 统计颜色直方图
            color_counts = {}
            for y in range(small.height()):
                for x in range(small.width()):
                    c = small.pixelColor(x, y)
                    if c.alpha() < 128:
                        continue
                    # 量化到 32 级，减少颜色数量
                    r = c.red() // 32 * 32
                    g = c.green() // 32 * 32
                    b = c.blue() // 32 * 32
                    key = (r, g, b)
                    color_counts[key] = color_counts.get(key, 0) + 1

            if not color_counts:
                return self._last_accent

            # 排除过暗和过亮的颜色
            best = max(
                color_counts.items(),
                key=lambda kv: kv[1] * self._color_weight(kv[0])
            )
            r, g, b = best[0]
            hex_color = f"#{r:02X}{g:02X}{b:02X}"
            self._last_accent = hex_color
            return hex_color
        except Exception as e:
            logger.debug(f"SMTC: extract accent failed: {e}")
            return self._last_accent

    @staticmethod
    def _color_weight(rgb):
        """给颜色一个权重：避免太暗或太亮的颜色被选中。"""
        r, g, b = rgb
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        if brightness < 40 or brightness > 220:
            return 0.1
        return 1.0

    def _apply_update(self, title, artist, art, position_ms, duration_ms, accent):
        if title != self._title:
            self._title = title
            self.titleChanged.emit()
        if artist != self._artist:
            self._artist = artist
            self.artistChanged.emit()
        if art != self._art:
            self._art = art
            self.artChanged.emit()

        # 进度
        self._position_ms = position_ms
        self._duration_ms = duration_ms
        new_progress = 0.0
        if duration_ms > 0:
            new_progress = max(0.0, min(1.0, position_ms / duration_ms))
        if abs(new_progress - self._progress) > 0.001:
            self._progress = new_progress
            self.progressChanged.emit()

        # 取色
        if accent != self._accent_color:
            self._accent_color = accent
            self.accentColorChanged.emit()
