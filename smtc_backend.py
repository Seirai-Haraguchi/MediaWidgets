"""
smtc_backend.py
SMTC Backend（Windows）
负责从 Windows SMTC (System Media Transport Controls) 获取当前媒体信息。

更新策略（沿用基类）：
- 订阅 SMTC 事件（换歌 / 播放暂停 / 进度跳变 / 会话切换）实现即时更新；
- 工作线程 asyncio 事件循环里拉取，经排队信号在主线程应用；
- 主线程 250ms 插值刷新播放进度；5s 兜底全量同步。
"""

import asyncio
import threading

from loguru import logger
from media_backend import MediaBackend


class SmtcBackend(MediaBackend):
    """Windows SMTC 媒体后端。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager_cls = None
        self._loop = None
        self._thread = None
        self._manager = None
        self._manager_token = None
        self._session = None
        self._session_id = None
        self._session_tokens = []

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

        super().start()  # 进度插值定时器 + _start_source()

    def _start_source(self):
        # asyncio 事件循环线程
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._bootstrap(), self._loop)

    def _resync(self):
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._light_sync(), self._loop)

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

            return self.process_art_bytes(bytes(raw))
        except Exception as e:
            logger.debug(f"SMTC: load album art failed: {e}")
            return ""
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
