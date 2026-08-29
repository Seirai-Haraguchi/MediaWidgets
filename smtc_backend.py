"""
smtc_backend.py
SMTC Backend
负责从 Windows SMTC (System Media Transport Controls) 获取当前媒体信息，
并通过 Qt 属性暴露给 QML。

更新策略：
- 订阅 SMTC 事件（换歌 / 播放暂停 / 进度跳变 / 会话切换）实现即时更新；
- 主线程 250ms 插值刷新播放进度，进度平滑移动不依赖轮询；
- 5s 兜底全量同步，纠正可能的漂移或漏掉的事件。
"""

import asyncio
import base64
import hashlib
import threading
import time

from loguru import logger
from PySide6.QtCore import QBuffer, QIODevice, QObject, Property, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath

# 专辑图输出尺寸与烘焙圆角（256px + 56px 圆角 ≈ 显示 36px 时视觉半径 8px，符合 M3 小组件观感）
_ART_SIZE = 256
_ART_RADIUS = 56

_TICK_MS = 250        # 进度插值刷新间隔
_RESYNC_MS = 5000     # 兜底同步间隔

# GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing
_STATUS_PLAYING = 4


class SmtcBackend(QObject):
    """向 QML 提供 SMTC 媒体信息的后端对象。"""

    # 属性变化信号
    titleChanged = Signal()
    artistChanged = Signal()
    artChanged = Signal()
    progressChanged = Signal()
    accentColorChanged = Signal()
    accentColor2Changed = Signal()

    # 换歌信号（title, artist）：供歌词推送等模块按歌曲触发
    songChanged = Signal(str, str)

    # 内部信号：工作线程 emit，经排队连接在主线程应用
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
        self._manager_cls = None
        self._loop = None
        self._thread = None
        self._tick_timer = None
        self._resync_timer = None
        self._manager = None
        self._manager_token = None
        self._session = None
        self._session_id = None
        self._session_tokens = []
        # 进度插值基准
        self._playing = False
        self._rate = 1.0
        self._pos_stamp = 0.0
        # 仅在工作线程访问：避免每次轮询重复编码相同的专辑图
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

    # ---- 启动 ----

    def start(self):
        """启动 SMTC 事件订阅与进度插值（在主线程调用）。"""
        if self._tick_timer is not None:
            return

        logger.info("SMTC: start() called, importing winrt...")
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager,
            )
            self._manager_cls = GlobalSystemMediaTransportControlsSessionManager
        except Exception as e:
            logger.error(f"SMTC: winrt import failed: {e}")
            return

        # asyncio 事件循环线程
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._bootstrap(), self._loop)

        # 主线程：进度插值（播放中每 250ms 刷新一次绑定）
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(_TICK_MS)

        # 主线程：兜底全量同步
        self._resync_timer = QTimer(self)
        self._resync_timer.timeout.connect(self._resync)
        self._resync_timer.start(_RESYNC_MS)
        logger.info(f"SMTC: started (tick={_TICK_MS}ms, resync={_RESYNC_MS}ms)")

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # ---- 事件订阅（工作线程 / WinRT 线程）----

    async def _bootstrap(self):
        try:
            manager = await self._manager_cls.request_async()
            self._manager = manager
            try:
                # 裸 Python 可调用可直接作为 WinRT 委托传入
                self._manager_token = manager.add_sessions_changed(self._on_sessions_changed)
            except Exception as e:
                logger.warning(f"SMTC: sessions_changed subscribe failed: {e}")
            await self._sync_state()
            logger.info("SMTC: event-driven mode ready")
        except Exception as e:
            logger.error(f"SMTC: bootstrap failed: {e}")

    def _on_sessions_changed(self, sender, args):
        """会话集合变化（应用开/关）：重建订阅并全量拉取。"""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._sync_state(), self._loop)

    def _on_any_session_event(self, sender, args):
        """任一会话的属性/播放/时间线事件：刷新当前会话并拉取。

        订阅全部会话而非仅当前会话——当前会话的切换（如另一应用开始播放）
        不一定伴随 sessions_changed 事件。
        """
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._light_sync(), self._loop)

    async def _sync_state(self):
        self._resubscribe_sessions()
        await self._fetch()

    async def _light_sync(self):
        self._update_current_session()
        await self._fetch()

    def _resubscribe_sessions(self):
        """退订全部旧会话事件，重新订阅当前所有会话。"""
        self._unsubscribe_sessions()
        try:
            sessions = list(self._manager.get_sessions())
        except Exception as e:
            logger.warning(f"SMTC: get_sessions failed: {e}")
            sessions = []
        for session in sessions:
            self._subscribe_session(session)
        self._update_current_session()

    def _subscribe_session(self, session):
        for name in (
            "media_properties_changed",
            "playback_info_changed",
            "timeline_properties_changed",
        ):
            try:
                token = getattr(session, f"add_{name}")(self._on_any_session_event)
                self._session_tokens.append((session, f"remove_{name}", token))
            except Exception as e:
                logger.warning(f"SMTC: subscribe {name} failed: {e}")

    def _unsubscribe_sessions(self):
        for session, remover, token in self._session_tokens:
            try:
                getattr(session, remover)(token)
            except Exception:
                pass
        self._session_tokens = []

    def _update_current_session(self):
        """刷新当前会话引用；当前会话可能在会话集合不变时切换。"""
        session = self._manager.get_current_session() if self._manager else None
        new_id = None
        if session is not None:
            try:
                new_id = session.source_app_user_model_id
            except Exception:
                new_id = None
        if new_id == self._session_id:
            return
        logger.info(f"SMTC: current session -> {new_id}")
        self._session = session
        self._session_id = new_id

    # ---- 数据拉取（工作线程）----

    def _resync(self):
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._light_sync(), self._loop)

    async def _fetch(self):
        try:
            session = self._session
            if session is None:
                self._mediaUpdated.emit("", "", "", 0, 0, *self._last_palette)
                self._playbackUpdated.emit(0, 1.0)
                self._timelineUpdated.emit(0, 0)
                return

            props = await session.try_get_media_properties_async()
            new_title = props.title or ""
            new_artist = props.artist or ""
            new_art = await self._load_art(props)

            position_ms, duration_ms = self._read_timeline(session)
            status, rate = self._read_playback(session)

            accent1, accent2 = self._last_palette
            if new_art:
                accent1, accent2 = self._extract_palette(new_art)

            logger.debug(
                f"SMTC: fetch title={new_title!r} pos={position_ms} dur={duration_ms} "
                f"status={status} art={bool(new_art)}"
            )
            self._mediaUpdated.emit(new_title, new_artist, new_art, position_ms, duration_ms, accent1, accent2)
            if status is not None:
                self._playbackUpdated.emit(status, rate if rate else 1.0)
            self._timelineUpdated.emit(position_ms, duration_ms)
        except Exception as e:
            logger.error(f"SMTC: fetch failed: {e}")

    def _read_timeline(self, session):
        """同步读取时间线，返回 (position_ms, duration_ms)；失败时保留旧值。"""
        try:
            ti = session.get_timeline_properties()
            pos = getattr(ti, "position", None)
            end = getattr(ti, "end_time", None)
            position_ms = int(pos.total_seconds() * 1000) if pos is not None else self._position_ms
            duration_ms = int(end.total_seconds() * 1000) if end is not None else self._duration_ms
            return position_ms, duration_ms
        except Exception as e:
            logger.debug(f"SMTC: get timeline failed: {e}")
            return self._position_ms, self._duration_ms

    @staticmethod
    def _read_playback(session):
        """同步读取播放状态，返回 (status, rate)；失败返回 (None, None)。"""
        try:
            pb = session.get_playback_info()
            status = int(pb.playback_status)
            rate = getattr(pb, "playback_rate", None)
            return status, (float(rate) if rate else None)
        except Exception as e:
            logger.debug(f"SMTC: get playback info failed: {e}")
            return None, None

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

            # 内容未变化时复用上次的 data URL，避免重复编码
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
            logger.debug(f"SMTC: extract palette failed: {e}")
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
        self._playing = (status == _STATUS_PLAYING)
        self._rate = rate if rate > 0 else 1.0
        self._pos_stamp = time.monotonic()
        self._emit_progress()
