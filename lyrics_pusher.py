"""
lyrics_pusher.py
滚动歌词推送器：监听 SMTC 换歌 → 网易云搜索匹配歌词 → 按播放进度
把当前歌词行实时推送到 Class Widgets 2 的动态通知组件。

推送原理（对应 CW2 源码 src/core/notification/）：
- NotificationProvider.push() 构造 NotificationData 后交给
  NotificationManager.dispatch()；
- dispatch() 在 data.silent 为 False 时播放提示音——逐行歌词推送必须
  绕开提示音，因此这里直接构造 silent=True 的 NotificationData 调
  provider.manager.dispatch()；
- CW2 运行时会向 ClassWidgets.SDK 注入真实的 NotificationData 类，
  开发环境（pip 安装的 SDK）没有，此时退化为等价的鸭子类型替身；
- 动态通知组件（dynamicNotification.qml）收到 notified 信号后用
  MarqueeTitle 滚动展示超宽文本，自动隐藏时间 = payload.duration。

时序：
- 换歌信号（主线程）→ 后台线程搜索匹配（不阻塞 UI）→ 信号回主线程应用；
- 复用 backend.progressChanged（播放中 4Hz 插值信号）作为节拍，用二分
  查找定位当前歌词行，行号变化才推送。
"""

import base64
import hashlib
import tempfile
import threading
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, QTimer, Signal

import netease_lyrics

try:
    # CW2 运行时注入的真实类；开发环境导入失败则走鸭子类型替身
    from ClassWidgets.SDK import NotificationData as _NotificationData
except Exception:
    _NotificationData = None

_FALLBACK_ICON = "ic_fluent_music_note_2_20_regular"  # 无专辑图时的 Fluent 图标
_MIN_LINE_MS = 1500     # 单行最短驻留（快歌连续滚动显示）
_MAX_LINE_MS = 15000    # 单行最长驻留（长间奏先隐藏，下一行到来再出现）
_TAIL_MS = 5000         # 末行驻留
_LINE_BUFFER_MS = 900   # 下一行到来前多停留一点，避免闪断
_CACHE_MAX = 200        # (title, artist) -> lines 缓存上限
_DEBOUNCE_MS = 800      # SMTC 换歌时标题/艺人可能分字段先后到达，合并成一次请求


class _DuckNotificationData:
    """开发环境下的 NotificationData 替身，只实现 dispatch() 会用到的字段。"""

    def __init__(self, provider_id, level, title, message, icon, duration, closable, silent):
        self.provider_id = provider_id
        self.level = level
        self.title = title
        self.message = message
        self.icon = icon
        self.duration = duration
        self.closable = closable
        self.silent = silent

    def model_dump(self):
        return {
            "provider_id": self.provider_id,
            "level": self.level,
            "title": self.title,
            "message": self.message,
            "icon": self.icon,
            "duration": self.duration,
            "closable": self.closable,
            "silent": self.silent,
            "use_system": False,
        }


class LyricsPusher(QObject):
    """把当前播放歌曲的逐行歌词推送到 CW2 动态通知。"""

    # 工作线程 → 主线程：generation, cache_key, lines
    _lyricsFetched = Signal(int, object, object)

    def __init__(self, provider, backend, config_getter=None, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._backend = backend
        # 实时配置读取函数：QML 设置页经 Configs.setPlugin 写入的是
        # configs.plugins.configs[pid] 字典（CW2 不会反向同步回注册的模型实例），
        # 因此这里每次调用都从配置管理器现读，保证开关立即生效。
        self._config_getter = config_getter
        self._gen = 0                 # 换代计数：换歌后丢弃过期的网络结果
        self._lines = []              # [(time_ms, text)]
        self._last_index = -1
        self._lines_key = None        # 当前 _lines 对应的 (title, artist)
        self._cache = {}              # 仅主线程读写
        self._icon_uri = _FALLBACK_ICON
        self._art_hash = None

        # SMTC 换歌时标题/艺人常分字段先后到达，同一首歌可能触发多次
        # songChanged；用防抖合并，避免同一首歌被重复抓取、当前行被重复推送
        self._debounce_title = ""
        self._debounce_artist = ""
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._do_fetch)

        backend.songChanged.connect(self._on_song_changed)
        backend.artChanged.connect(self._on_art_changed)
        backend.progressChanged.connect(self._on_progress_tick)
        self._lyricsFetched.connect(self._apply_lyrics)

    # ---- 换歌：触发歌词获取 ----

    def _on_song_changed(self, title, artist):
        self._gen += 1
        self._lines = []
        self._last_index = -1
        self._lines_key = None
        self._refresh_icon(self._backend.art)
        if not title or not self._lyrics_enabled():
            return

        self._debounce_title = title
        self._debounce_artist = artist or ""
        self._debounce_timer.start()

    def _do_fetch(self):
        if not self._lyrics_enabled():
            return
        title = self._debounce_title
        artist = self._debounce_artist
        key = (title, artist)
        if key in self._cache:
            self._lines = self._cache[key]
            self._lines_key = key
            return
        gen = self._gen
        duration_ms = self._backend.duration_ms
        threading.Thread(
            target=self._fetch_worker,
            args=(gen, key, title, artist, duration_ms),
            daemon=True,
        ).start()

    def _fetch_worker(self, gen, key, title, artist, duration_ms):
        try:
            song, lines = netease_lyrics.find_lyrics(title, artist, duration_ms)
        except Exception as e:
            # 网络失败不缓存，下次换歌（或切回这首歌）还能重试
            logger.warning(f"Lyrics: network error for {title!r}: {e}")
            return
        if gen != self._gen:
            return  # 歌已经换了，丢弃过期结果
        if song is None:
            logger.info(f"Lyrics: no match on NetEase for {title!r} / {artist!r}")
        else:
            logger.info(
                f"Lyrics: matched {song.get('name')!r} (id={song.get('id')}), "
                f"{len(lines)} lines"
            )
        self._lyricsFetched.emit(gen, key, lines)

    def _apply_lyrics(self, gen, key, lines):
        if gen != self._gen:
            return
        self._cache[key] = lines
        while len(self._cache) > _CACHE_MAX:
            del self._cache[next(iter(self._cache))]
        already_shown = key == self._lines_key  # 同歌重复应用：不重置行号，避免当前行重推
        self._lines = list(lines)
        self._lines_key = key
        if not already_shown:
            self._last_index = -1

    # ---- 进度驱动：逐行推送 ----

    def _lyrics_enabled(self):
        """灵动通知歌词总开关（设置页可关闭，关闭后完全不推送歌词）。"""
        return self._read_config("lyrics_enabled", True)

    def _show_translation(self):
        """翻译显示开关（设置页可关闭，关闭后只推原文）。"""
        return self._read_config("show_translation", True)

    def _read_config(self, key, default):
        getter = self._config_getter
        if getter is None:
            return default
        try:
            value = getter(key)
        except Exception as e:
            logger.debug(f"Lyrics: read config {key!r} failed: {e}")
            return default
        return default if value is None else value

    def _on_progress_tick(self):
        if not self._lyrics_enabled():
            self._last_index = -1
            return
        if not self._lines:
            return
        idx = self._index_at(self._backend.current_position_ms())
        if idx != self._last_index:
            self._last_index = idx
            if idx >= 0:
                self._push_line(idx)

    def _index_at(self, pos_ms):
        """二分查找：最后一个 time_ms <= pos 的行号；都在 pos 之前返回 -1。"""
        lo, hi = 0, len(self._lines)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._lines[mid][0] <= pos_ms:
                lo = mid + 1
            else:
                hi = mid
        return lo - 1

    def _push_line(self, idx):
        t, text, trans = self._lines[idx]
        if idx + 1 < len(self._lines):
            stay = self._lines[idx + 1][0] - t + _LINE_BUFFER_MS
        else:
            stay = _TAIL_MS
        stay = int(max(_MIN_LINE_MS, min(_MAX_LINE_MS, stay)))
        # 原文进标题槽，翻译进消息槽（翻译关闭时仅原文一行）；无翻译时原文直接进消息槽
        if trans and self._show_translation():
            self._dispatch(text, trans, stay)
        else:
            self._dispatch("", text, stay)

    def _dispatch(self, title, message, duration):
        provider = self._provider
        if provider is None:
            return
        icon = self._icon_uri or None
        try:
            if _NotificationData is not None:
                data = _NotificationData(
                    provider_id=provider.id,
                    level=0,  # INFO → 动态通知组件按主题色渲染
                    title=title,
                    message=message,
                    icon=icon,
                    duration=duration,
                    closable=False,
                    silent=True,
                )
            else:
                data = _DuckNotificationData(
                    provider.id, 0, title, message, icon, duration, False, True
                )
            provider.manager.dispatch(data)
        except Exception as e:
            logger.debug(f"Lyrics: push failed: {e}")

    # ---- 专辑图图标 ----

    def _on_art_changed(self):
        self._refresh_icon(self._backend.art)

    def _refresh_icon(self, art_data_url):
        """把专辑图落到临时文件，用 file:// URI 作为通知图标（QML 只认 URL 型图标）。"""
        if not art_data_url or not art_data_url.startswith("data:image/"):
            self._icon_uri = _FALLBACK_ICON
            self._art_hash = None
            return
        try:
            _, b64 = art_data_url.split(",", 1)
            raw = base64.b64decode(b64)
        except Exception:
            self._icon_uri = _FALLBACK_ICON
            return
        digest = hashlib.md5(raw).hexdigest()[:16]
        if digest == self._art_hash:
            return
        try:
            art_dir = Path(tempfile.gettempdir()) / "cw-mediawidgets"
            art_dir.mkdir(parents=True, exist_ok=True)
            path = art_dir / f"art-{digest}.png"
            if not path.exists():
                path.write_bytes(raw)
            self._cleanup_art_dir(art_dir, current=path)
            self._icon_uri = path.as_uri()
            self._art_hash = digest
        except Exception as e:
            logger.debug(f"Lyrics: write art icon failed: {e}")
            self._icon_uri = _FALLBACK_ICON

    @staticmethod
    def _cleanup_art_dir(art_dir, current, keep=8):
        try:
            files = [p for p in art_dir.glob("art-*.png") if p != current]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for p in files[keep - 1:]:
                p.unlink(missing_ok=True)
        except Exception:
            pass
