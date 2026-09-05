"""
lyrics_backend.py
歌词组件后端：监听媒体后端换歌 → 后台线程按所选歌词源抓取（磁盘缓存优先）→
向 QML 歌词组件（qml/LyricsWidget.qml）提供当前行逐字数据、翻译/下一行副行、
进度节拍等动态属性。

- 完全不动灵动通知：渲染全部在插件自己的歌词小组件里完成；
- 逐字歌词（QQ QRC / 酷狗 KRC）输出 word 级 [{text, startMs, endMs}]，
  行级歌词（网易云 LRC）输出整行单 word —— QML 统一用「填充扫描」卡拉OK动画；
- 副行规则：当前行有翻译且开启翻译 → 显示翻译；否则显示下一行歌词预览；
- 歌词源可在设置页切换（auto/QQ/酷狗/网易云），切换后对当前歌曲立即重抓。

线程模型：换歌信号（主线程）→ 防抖合并 → 工作线程搜索抓取 → 排队信号回主线程
应用；generation 计数丢弃换歌后的过期结果。磁盘缓存写在用户缓存目录
（%LOCALAPPDATA%/ClassWidgets/MediaWidgets 或 ~/.cache/MediaWidgets），
不落在插件目录（插件目录可能被杀软/资源管理器锁住，见 v1.6.3 教训）。
"""

import hashlib
import json
import os
import sys
import threading
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, Property, QTimer, Signal

import lyrics_providers

_TICK_MS = 100        # 进度节拍：驱动逐字填充动画
_DEBOUNCE_MS = 800    # 换歌防抖：SMTC 标题/艺人常分字段先后到达
_CACHE_MAX = 300      # 磁盘缓存条目上限（超出按最旧淘汰）


def _default_cache_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "ClassWidgets" / "MediaWidgets" / "lyrics_cache"
    return Path.home() / ".cache" / "MediaWidgets" / "lyrics_cache"


# ---- 磁盘缓存序列化 ----

def doc_to_json(doc):
    return {
        "version": 1,
        "source": doc.source,
        "song": doc.song_name,
        "lines": [
            {
                "s": ln.start_ms,
                "e": ln.end_ms,
                "t": ln.text,
                "tr": ln.translation,
                "w": [[w.start_ms, w.end_ms, w.text] for w in ln.words],
            }
            for ln in doc.lines
        ],
    }


def doc_from_json(data):
    lines = [
        lyrics_providers.LyricLine(
            ln["s"], ln["e"], ln["t"],
            words=[lyrics_providers.LyricWord(s, e, t) for s, e, t in ln.get("w") or []],
            translation=ln.get("tr"),
        )
        for ln in data.get("lines") or []
    ]
    return lyrics_providers.LyricsDocument(lines, data.get("source", ""), data.get("song", ""))


class LyricsBackend(QObject):
    """歌词小组件的 backend 对象：进度节拍 + 当前行/逐字/副行动态属性。"""

    # 工作线程 → 主线程：generation, doc|None, 请求源, 实际命中源, error
    _fetched = Signal(int, object, str, str, str)

    # ---- QML 属性变化信号 ----
    stateChanged = Signal()
    lineChanged = Signal()       # lineText / words / subLine / subIsTranslation 一起换
    positionChanged = Signal()
    sourceNameChanged = Signal()

    def __init__(self, media_backend, config_getter=None, cache_dir=None,
                 fetch_func=None, parent=None):
        super().__init__(parent)
        self._media = media_backend
        self._config_getter = config_getter
        self._fetch_func = fetch_func or lyrics_providers.fetch_document
        self._cache_dir = Path(cache_dir) if cache_dir else _default_cache_dir()

        self._state = "idle"     # idle | loading | ready | nomatch | error
        self._doc = None
        self._lines = []
        self._index = -1
        self._position_ms = 0
        self._gen = 0
        self._title = ""
        self._artist = ""
        self._source_name = ""
        self._applied_source = None   # 当前 _doc 对应的请求源（含 "auto"）
        self._last_show_translation = None  # None = 尚未读过（避免首帧误判成"变了"）

        self._words = []         # QVariantList：[{text, startMs, endMs}]
        self._line_text = ""
        self._sub_line = ""
        self._sub_is_translation = False

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._do_fetch)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(_TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)

        self._fetched.connect(self._apply_fetched)
        if media_backend is not None:
            media_backend.songChanged.connect(self._on_song_changed)

    # ---- 生命周期 ----

    def start(self):
        if self._tick_timer.isActive():
            return
        self._tick_timer.start()
        # 媒体后端先于本对象启动时，songChanged 已错过：手动补一次
        if self._media is not None and getattr(self._media, "title", "") and not self._title:
            self._on_song_changed(self._media.title, getattr(self._media, "artist", ""))
        self._on_tick()   # 立即同步一次当前状态（可能设置页打开时已在播）

    def stop(self):
        self._tick_timer.stop()
        self._debounce_timer.stop()

    # ---- QML 属性 ----

    @Property(QObject, constant=True)
    def media(self):
        """媒体后端对象：QML 由此取封面/主色/进度等（引用恒定，不变化）。"""
        return self._media

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Property(str, notify=lineChanged)
    def lineText(self):
        return self._line_text

    @Property("QVariantList", notify=lineChanged)
    def words(self):
        return self._words

    @Property(str, notify=lineChanged)
    def subLine(self):
        return self._sub_line

    @Property(bool, notify=lineChanged)
    def subIsTranslation(self):
        return self._sub_is_translation

    @Property(int, notify=positionChanged)
    def positionMs(self):
        return self._position_ms

    @Property(str, notify=sourceNameChanged)
    def sourceName(self):
        return self._source_name

    # ---- 配置读取（实时，设置页改动立即生效） ----

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

    def _configured_source(self):
        source = self._read_config("lyric_source", "auto")
        return source if source in lyrics_providers.AUTO_ORDER else "auto"

    def _show_translation(self):
        return bool(self._read_config("show_translation", True))

    # ---- 换歌：触发歌词获取 ----

    def _on_song_changed(self, title, artist):
        self._gen += 1
        self._doc = None
        self._lines = []
        self._index = -1
        self._applied_source = None
        self._title = title or ""
        self._artist = artist or ""
        self._set_state("idle")
        self._clear_line()
        if not self._title:
            return
        self._set_state("loading")
        self._debounce_timer.start()

    def _do_fetch(self):
        if not self._title:
            return
        title, artist = self._title, self._artist
        source = self._configured_source()
        duration_ms = self._media.duration_ms if self._media is not None else 0
        gen = self._gen

        cached = self._load_cache(title, artist, duration_ms, source)
        if cached is not None:
            self._apply_fetched(gen, cached, source, cached.source, "")
            return
        self._set_state("loading")
        threading.Thread(
            target=self._fetch_worker,
            args=(gen, title, artist, duration_ms, source),
            daemon=True,
        ).start()

    def _fetch_worker(self, gen, title, artist, duration_ms, source):
        try:
            doc, used = self._fetch_func(title, artist, duration_ms, source)
        except Exception as e:
            logger.warning(f"Lyrics: fetch error for {title!r} ({source}): {e}")
            self._fetched.emit(gen, None, source, source, str(e))
            return
        if gen != self._gen:
            return
        if doc is not None:
            self._save_cache(title, artist, duration_ms, source, doc)
        self._fetched.emit(gen, doc, source, used or source, "")

    def _apply_fetched(self, gen, doc, requested_source, used_source, error):
        if gen != self._gen:
            return
        # 按请求时的源记账：抓取期间用户改了源，_poll_config 会发现不一致并重抓
        self._applied_source = requested_source
        if doc is None or not doc.lines:
            self._doc = None
            self._lines = []
            self._index = -1
            self._source_name = ""
            self.sourceNameChanged.emit()
            self._set_state("error" if error else "nomatch")
            self._clear_line()
            return
        self._doc = doc
        self._lines = doc.lines
        self._index = -1
        self._source_name = lyrics_providers.SOURCE_NAMES.get(doc.source, doc.source)
        self.sourceNameChanged.emit()
        self._set_state("ready")
        logger.info(
            f"Lyrics: {doc.song_name!r} via {doc.source}, "
            f"{len(doc.lines)} lines, word_timing={doc.has_word_timing}"
        )
        self._sync_line(force=True)

    # ---- 进度节拍：更新 positionMs、定位当前行、轮询配置变化 ----

    def _on_tick(self):
        if self._media is not None:
            self._position_ms = int(self._media.current_position_ms())
        else:
            self._position_ms = 0
        self.positionChanged.emit()

        self._poll_config()
        if self._lines:
            self._sync_line()

    def _poll_config(self):
        """设置页改动立即生效：翻译开关 → 重算副行；歌词源 → 对当前歌曲重抓。"""
        show_trans = self._show_translation()
        if self._last_show_translation is not None and show_trans != self._last_show_translation:
            self._sync_line(force=True)
        self._last_show_translation = show_trans

        source = self._configured_source()
        if (self._title and self._applied_source is not None
                and source != self._applied_source):
            logger.info(f"Lyrics: source changed {self._applied_source!r} -> {source!r}, refetching")
            self._applied_source = None
            self._set_state("loading")
            self._debounce_timer.start()

    def _sync_line(self, force=False):
        idx = self._index_at(self._position_ms)
        if idx < 0 and self._lines:
            idx = 0  # 前奏：显示第一行未填充预览（fillRatio=0），唱到自然开始扫描
        if not force and idx == self._index:
            return
        self._index = idx
        if idx < 0:
            self._clear_line()
            return
        self._apply_line(idx)

    def _index_at(self, pos_ms):
        """二分：最后一个 start_ms <= pos 的行号；都在 pos 之前返回 -1。"""
        lo, hi = 0, len(self._lines)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._lines[mid].start_ms <= pos_ms:
                lo = mid + 1
            else:
                hi = mid
        return lo - 1

    def _apply_line(self, idx):
        ln = self._lines[idx]
        self._line_text = ln.text

        # 逐字行输出 word 列表；行级歌词整行一个 word（QML 同一套填充扫描）
        if ln.words:
            self._words = [
                {"text": w.text, "startMs": w.start_ms, "endMs": w.end_ms}
                for w in ln.words
            ]
        else:
            self._words = [{"text": ln.text, "startMs": ln.start_ms, "endMs": ln.end_ms}]

        # 副行：有翻译且开启 → 翻译；否则下一行预览
        if ln.translation and self._show_translation():
            self._sub_line = ln.translation
            self._sub_is_translation = True
        else:
            nxt = self._lines[idx + 1] if idx + 1 < len(self._lines) else None
            self._sub_line = nxt.text if nxt is not None else ""
            self._sub_is_translation = False

        self.lineChanged.emit()

    def _clear_line(self):
        if not self._line_text and not self._words and not self._sub_line:
            return
        self._line_text = ""
        self._words = []
        self._sub_line = ""
        self._sub_is_translation = False
        self.lineChanged.emit()

    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self.stateChanged.emit()

    # ---- 磁盘缓存 ----

    def _cache_path(self, title, artist, duration_ms, source):
        key = f"{title}\x00{artist}\x00{duration_ms // 1000}\x00{source}"
        return self._cache_dir / (hashlib.md5(key.encode("utf-8")).hexdigest() + ".json")

    def _load_cache(self, title, artist, duration_ms, source):
        path = self._cache_path(title, artist, duration_ms, source)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            doc = doc_from_json(data)
            if doc.lines:
                return doc
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug(f"Lyrics: cache read failed ({path.name}): {e}")
        return None

    def _save_cache(self, title, artist, duration_ms, source, doc):
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_path(title, artist, duration_ms, source)
            path.write_text(
                json.dumps(doc_to_json(doc), ensure_ascii=False), encoding="utf-8")
            self._evict_cache()
        except Exception as e:
            # 缓存写失败不影响功能（磁盘满/权限），只是下次要重新联网
            logger.debug(f"Lyrics: cache write failed: {e}")

    def _evict_cache(self):
        try:
            entries = sorted(self._cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
            for path in entries[:max(0, len(entries) - _CACHE_MAX)]:
                path.unlink(missing_ok=True)
        except Exception:
            pass
