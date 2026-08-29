"""
mpris_backend.py
MPRIS Backend（Linux）
通过 D-Bus（PySide6.QtDBus，宿主自带，无新增依赖）监听 MPRIS 媒体会话：
- 自动发现 org.mpris.MediaPlayer2.* 播放器，订阅 PropertiesChanged / Seeked；
- 选择当前活跃播放器：优先正在播放的，其次最近有活动的；
- 进度：以 Position + Seeked 事件更新基准，沿用基类 250ms 插值平滑前进；
- 封面：file:// 与 data: 同步读取，http(s):// 后台线程下载后经信号回填。

所有事件处理都在 Qt 主线程（QtDBus 信号经事件循环派发），
因此直接调用基类的 _apply_* 方法应用状态，无需排队信号。
"""

import base64
import threading
import time

from loguru import logger
from PySide6.QtCore import QUrl, Signal
from PySide6.QtDBus import (
    QDBusArgument,
    QDBusConnection,
    QDBusInterface,
    QDBusVariant,
)

from media_backend import MediaBackend, _STATUS_PLAYING

_IFACE_PLAYER = "org.mpris.MediaPlayer2.Player"
_IFACE_PROPERTIES = "org.freedesktop.DBus.Properties"
_PATH = "/org/mpris/MediaPlayer2"
_PREFIX = "org.mpris.MediaPlayer2."


class MprisBackend(MediaBackend):
    """Linux MPRIS 媒体后端。"""

    # 后台线程取回封面后回填（data_url, 请求时的歌曲标识）
    _artReady = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bus = None
        self._started = False
        self._players = {}        # service -> 最近活动时间戳（monotonic）
        self._ifaces = {}         # service -> QDBusInterface（Player 接口）
        self._active = None
        self._session = None
        self._session_service = None
        self._artReady.connect(self._on_art_ready)

    # ---- 启动 ----

    def _start_source(self):
        if not QDBusConnection.sessionBus().isConnected():
            logger.warning("MPRIS: no D-Bus session bus, backend inactive")
            return
        self._bus = QDBusConnection.sessionBus()
        try:
            self._bus.interface().serviceOwnerChanged.connect(
                self._on_service_owner_changed
            )
        except Exception as e:
            logger.warning(f"MPRIS: serviceOwnerChanged subscribe failed: {e}")
        self._discover_players()
        self._started = True
        logger.info("MPRIS: started")
        self._refresh()

    def _resync(self):
        self._refresh()

    # ---- 播放器发现与订阅 ----

    def _discover_players(self):
        iface = self._bus.interface()
        names = self._list_service_names(iface)
        for n in names:
            if isinstance(n, str) and n.startswith(_PREFIX):
                self._add_player(n)
        if names:
            logger.info(f"MPRIS: discovered {len(self._players)} player(s)")

    @staticmethod
    def _list_service_names(iface):
        try:
            names = iface.registeredServiceNames()
        except TypeError:
            try:
                names = iface.registeredServiceNames
            except Exception:
                return []
        if hasattr(names, "value"):
            try:
                names = names.value()
            except Exception:
                return []
        return list(names) if isinstance(names, (list, tuple)) else []

    def _add_player(self, service):
        if service in self._players:
            return
        self._players[service] = time.monotonic()
        self._ifaces[service] = QDBusInterface(service, _PATH, _IFACE_PLAYER, self._bus)
        try:
            self._bus.connect(
                service, _PATH, _IFACE_PROPERTIES, "PropertiesChanged",
                self._make_properties_handler(service),
            )
            self._bus.connect(
                service, _PATH, _IFACE_PLAYER, "Seeked",
                self._make_seeked_handler(service),
            )
        except Exception as e:
            logger.warning(f"MPRIS: subscribe {service} failed: {e}")
        logger.info(f"MPRIS: player added: {service}")

    def _make_properties_handler(self, service):
        def handler(interface_name, changed, invalidated):
            self._on_properties_changed(service, interface_name, changed, invalidated)

        return handler

    def _make_seeked_handler(self, service):
        def handler(position_us):
            self._on_seeked(service, position_us)

        return handler

    def _on_service_owner_changed(self, service, old_owner, new_owner):
        if not service.startswith(_PREFIX):
            return
        if new_owner:
            self._add_player(service)
        else:
            self._players.pop(service, None)
            self._ifaces.pop(service, None)
            if self._active == service:
                self._active = None
                self._session = None
                self._session_service = None
        self._refresh()

    def _on_properties_changed(self, service, interface_name, changed, invalidated):
        if interface_name != _IFACE_PLAYER or service not in self._players:
            return
        self._players[service] = time.monotonic()
        self._refresh()

    def _on_seeked(self, service, position_us):
        if service not in self._players:
            return
        self._players[service] = time.monotonic()
        try:
            pos_ms = int(position_us) // 1000
        except (TypeError, ValueError):
            pos_ms = self._position_ms
        # Seeked 是权威位置通知（播放器可能异步更新 Position 属性），直接用事件值
        self._apply_timeline(pos_ms, self._duration_ms)
        self._apply_playback(self._read_status(), self._read_rate())

    # ---- 状态拉取与应用 ----

    def _refresh(self):
        self._refresh_active()
        if self._active is None:
            self._apply_update("", "", "", 0, 0, *self._last_palette)
            self._apply_playback(0, 1.0)
            self._apply_timeline(0, 0)
            return
        svc = self._active
        if self._session_service != svc:
            self._session = self._ifaces.get(svc)
            self._session_service = svc
        if self._session is None:
            return
        status = self._read_status()
        rate = self._read_rate()
        meta = self._read_metadata()
        pos = self._read_position()
        self._handle_metadata(meta)
        self._apply_playback(status, rate)
        self._apply_timeline(pos, self._duration_ms)

    def _refresh_active(self):
        if not self._players:
            self._active = None
            return
        playing = [s for s in self._players if self._is_playing(s)]
        pool = playing or sorted(self._players, key=lambda s: self._players[s], reverse=True)
        self._active = pool[0]

    def _is_playing(self, service):
        iface = self._ifaces.get(service)
        if iface is None:
            return False
        try:
            v = self._unwrap(iface.property("PlaybackStatus"))
        except Exception:
            return False
        return v == "Playing"

    def _get_property(self, name):
        if self._session is None:
            return None
        try:
            return self._unwrap(self._session.property(name))
        except Exception as e:
            logger.debug(f"MPRIS: property {name} failed: {e}")
            return None

    def _read_status(self):
        return _STATUS_PLAYING if self._get_property("PlaybackStatus") == "Playing" else 0

    def _read_rate(self):
        v = self._get_property("Rate")
        return float(v) if isinstance(v, (int, float)) and float(v) > 0 else 1.0

    def _read_position(self):
        v = self._get_property("Position")
        if isinstance(v, int) and v >= 0:
            return v // 1000  # μs -> ms
        return self._position_ms

    def _read_metadata(self):
        v = self._get_property("Metadata")
        return v if isinstance(v, dict) else {}

    @staticmethod
    def _unwrap(v):
        """递归把 QtDBus 包装类型转成 Python 对象。"""
        if isinstance(v, QDBusVariant):
            return MprisBackend._unwrap(v.variant())
        if isinstance(v, QDBusArgument):
            try:
                return MprisBackend._unwrap(v.asVariant())
            except Exception:
                return str(v)
        if isinstance(v, dict):
            return {str(k): MprisBackend._unwrap(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [MprisBackend._unwrap(x) for x in v]
        return v

    # ---- 元数据应用 ----

    def _handle_metadata(self, meta):
        title = str(meta.get("xesam:title") or "")
        artist = self._artist_from_meta(meta)
        art_url = str(meta.get("mpris:artUrl") or "")
        length = meta.get("mpris:length")
        duration_ms = (
            int(length / 1000) if isinstance(length, int) and length > 0
            else self._duration_ms
        )
        if not title and not artist and not art_url and not length:
            return

        art = ""
        if art_url:
            if art_url == self._last_art_url:
                art = self._art  # 同一封面：复用
            else:
                raw = self._resolve_art_bytes(art_url, (title, artist))
                if raw is not None:
                    art = self._rounded_png_data_url(raw)
                    if art:
                        self._last_art_url = art_url
                # raw is None（HTTP 下载中/失败）→ art 保持空，稍后经 _artReady 回填

        if art:
            accent1, accent2 = self._extract_palette(art)
        else:
            accent1, accent2 = self._last_palette
        self._apply_update(title, artist, art, self._position_ms, duration_ms, accent1, accent2)

    @staticmethod
    def _artist_from_meta(meta):
        a = meta.get("xesam:artist") or meta.get("xesam:albumArtist") or ""
        if isinstance(a, (list, tuple)):
            return ", ".join(str(x) for x in a if x)
        return str(a) if a else ""

    # ---- 封面解析 ----

    def _resolve_art_bytes(self, url, key):
        """把 mpris:artUrl 解析为图片字节；HTTP 走后台线程，返回 None。"""
        if url.startswith("data:"):
            try:
                _, b64 = url.split(",", 1)
                return base64.b64decode(b64)
            except Exception:
                return None
        if url.startswith("file:"):
            p = QUrl(url).toLocalFile()
            try:
                with open(p, "rb") as f:
                    return f.read()
            except OSError:
                return None
        if url.startswith(("http://", "https://")):
            threading.Thread(target=self._fetch_http_art, args=(url, key), daemon=True).start()
            return None
        return None

    def _fetch_http_art(self, url, key):
        try:
            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "MediaWidgets/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read(12 * 1024 * 1024)
            data_url = self._rounded_png_data_url(raw)
            if not data_url:
                raise ValueError("bad image")
            self._artReady.emit(data_url, key)
        except Exception as e:
            logger.debug(f"MPRIS: HTTP art failed: {e}")
            self._artReady.emit("", key)

    def _on_art_ready(self, data_url, key):
        if (self._title, self._artist) != key:
            return  # 歌曲已切换，丢弃过期封面
        if not data_url:
            return
        accent1, accent2 = self._extract_palette(data_url)
        self._apply_update(
            self._title, self._artist, data_url,
            self._position_ms, self._duration_ms, accent1, accent2,
        )
