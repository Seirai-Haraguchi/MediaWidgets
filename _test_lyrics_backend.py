"""LyricsBackend 逻辑单测：假媒体后端 + 假抓取函数，验证逐字/副行/状态/缓存/源切换。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QCoreApplication, QObject, Signal

app = QCoreApplication([])

import lyrics_providers as lp
from lyrics_backend import LyricsBackend, doc_from_json, doc_to_json

fails = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        fails.append(name)


class FakeMedia(QObject):
    songChanged = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.title = ""
        self.artist = ""
        self.duration_ms = 200000
        self._pos = 0

    def current_position_ms(self):
        return self._pos


def make_doc():
    """两行逐字歌词：第一行带翻译，第二行无翻译。"""
    return lp.LyricsDocument([
        lp.LyricLine(1000, 3000, "晴天 周杰伦",
                     [lp.LyricWord(1000, 1600, "晴天"),
                      lp.LyricWord(1600, 2600, " "),
                      lp.LyricWord(2600, 3800, "周杰伦")],
                     translation="Sunny day"),
        lp.LyricLine(5000, 3000, "词 周杰伦",
                     [lp.LyricWord(5000, 6000, "词")],
                     translation=None),
    ], "qqmusic", "晴天")


def make_backend(config=None, fetch=None, cache_dir=None):
    cfg = dict(config or {})
    media = FakeMedia()

    def getter(key):
        return cfg.get(key)

    backend = LyricsBackend(media, getter, cache_dir=cache_dir or tempfile.mkdtemp(),
                            fetch_func=fetch)
    return backend, media, cfg


def test_word_line_and_translation():
    backend, media, _ = make_backend(fetch=lambda *a: (make_doc(), "qqmusic"))
    media.title, media.artist = "晴天", "周杰伦"
    backend._on_song_changed("晴天", "周杰伦")
    check("state loading after song change", backend.state == "loading", backend.state)
    # 直接同步调用 worker（测试不走线程与防抖定时器）
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")

    check("state ready", backend.state == "ready", backend.state)
    check("source name", backend.sourceName == "QQ音乐", backend.sourceName)

    media._pos = 0  # 前奏：显示第一行预览
    backend._on_tick()
    check("intro preview line0", backend.lineText == "晴天 周杰伦", backend.lineText)
    check("intro preview words", [w["text"] for w in backend.words] == ["晴天", " ", "周杰伦"],
          str(backend.words))
    check("intro sub is translation", backend.subLine == "Sunny day" and backend.subIsTranslation)

    media._pos = 1200  # 第一行内："晴"唱到一半
    backend._on_tick()
    check("position exposed", backend.positionMs == 1200)
    w0 = backend.words[0]
    check("word timing", (w0["text"], w0["startMs"], w0["endMs"]) == ("晴天", 1000, 1600), str(w0))

    media._pos = 5500  # 第二行：无翻译 → 下一行预览？第二行是最后一行 → 空
    backend._on_tick()
    check("line1 text", backend.lineText == "词 周杰伦", backend.lineText)
    check("last line sub empty", backend.subLine == "" and not backend.subIsTranslation)


def test_no_translation_falls_to_next_line():
    backend, media, _ = make_backend(config={"show_translation": False},
                                     fetch=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")

    # 第一行有翻译但开关关闭 → 下一行预览
    media._pos = 1500
    backend._on_tick()
    check("translation off -> next line",
          backend.subLine == "词 周杰伦" and not backend.subIsTranslation,
          f"{backend.subLine!r} trans={backend.subIsTranslation}")

    # 中间行（非末行）无翻译 → 下一行预览
    doc = make_doc()
    doc.lines.append(lp.LyricLine(9000, 2000, "尾行", [], "Last"))
    backend3, media3, _ = make_backend(fetch=lambda *a: (doc, "qqmusic"))
    backend3._on_song_changed("晴天", "周杰伦")
    backend3._fetch_worker(backend3._gen, "晴天", "周杰伦", media3.duration_ms, "auto")
    media3._pos = 5500
    backend3._on_tick()
    check("mid line no translation -> next line", backend3.subLine == "尾行",
          backend3.subLine)


def test_line_level_doc_single_word():
    """行级歌词（网易云 LRC）→ 整行一个 word，QML 同一套扫描动画。"""
    doc = lp.LyricsDocument([
        lp.LyricLine(0, 4000, "第一行", [], None),
        lp.LyricLine(4000, 4000, "第二行", [], "Line 2"),
    ], "netease", "歌")
    backend, media, _ = make_backend(fetch=lambda *a: (doc, "netease"))
    backend._on_song_changed("歌", "艺")
    backend._fetch_worker(backend._gen, "歌", "艺", media.duration_ms, "auto")
    media._pos = 1000
    backend._on_tick()
    check("line-level single word",
          backend.words == [{"text": "第一行", "startMs": 0, "endMs": 4000}],
          str(backend.words))
    # 第一行无翻译 → 下一行预览
    check("line-level next-line preview", backend.subLine == "第二行", backend.subLine)
    media._pos = 5000
    backend._on_tick()
    check("line-level sub translation", backend.subLine == "Line 2", backend.subLine)


def test_seek_updates_line():
    backend, media, _ = make_backend(fetch=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")
    media._pos = 1200
    backend._on_tick()
    media._pos = 5500  # 快进
    backend._on_tick()
    check("seek moves to line1", backend.lineText == "词 周杰伦")
    media._pos = 1200  # 快退
    backend._on_tick()
    check("seek back moves to line0", backend.lineText == "晴天 周杰伦")


def test_stale_generation_discarded():
    backend, media, _ = make_backend(fetch=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    stale_gen = backend._gen
    backend._on_song_changed("Lemon", "米津玄師")  # 抓取期间换歌
    backend._fetched.emit(stale_gen, make_doc(), "auto", "qqmusic", "")
    check("stale result dropped", backend.state == "loading" and backend.lineText == "",
          backend.state)


def test_nomatch_and_error_states():
    backend, media, _ = make_backend(fetch=lambda *a: (None, None))
    backend._on_song_changed("无", "歌")
    backend._fetch_worker(backend._gen, "无", "歌", media.duration_ms, "auto")
    check("nomatch state", backend.state == "nomatch", backend.state)

    def boom(*a):
        raise RuntimeError("network down")
    backend2, media2, _ = make_backend(fetch=boom)
    backend2._on_song_changed("无", "歌")
    backend2._fetch_worker(backend2._gen, "无", "歌", media2.duration_ms, "auto")
    check("error state", backend2.state == "error", backend2.state)


def test_cache_roundtrip_and_hit():
    cache_dir = tempfile.mkdtemp()
    calls = {"n": 0}

    def counting_fetch(*a):
        calls["n"] += 1
        return make_doc(), "qqmusic"

    b1, media1, _ = make_backend(fetch=counting_fetch, cache_dir=cache_dir)
    b1._on_song_changed("晴天", "周杰伦")
    b1._fetch_worker(b1._gen, "晴天", "周杰伦", media1.duration_ms, "auto")
    check("first fetch hits network", calls["n"] == 1, f"calls={calls['n']}")

    # 第二个实例（模拟重启后）：磁盘缓存命中，不再联网
    b2, media2, _ = make_backend(fetch=counting_fetch, cache_dir=cache_dir)
    b2._on_song_changed("晴天", "周杰伦")
    b2._do_fetch()  # 缓存命中路径是同步的，直接生效
    check("cache hit avoids network", calls["n"] == 1, f"calls={calls['n']}")
    check("cache hit state ready", b2.state == "ready", b2.state)
    media2._pos = 1200
    b2._on_tick()
    check("cached doc renders", b2.lineText == "晴天 周杰伦", b2.lineText)


def test_source_change_triggers_refetch():
    cfg = {"lyric_source": "auto"}
    media = FakeMedia()

    def getter(key):
        return cfg.get(key)

    calls = []

    def fetch(title, artist, dur, source):
        calls.append(source)
        return make_doc(), "qqmusic"

    backend = LyricsBackend(media, getter, cache_dir=tempfile.mkdtemp(), fetch_func=fetch)
    backend._on_song_changed("晴天", "周杰伦")
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")
    check("fetched with auto", calls == ["auto"], str(calls))

    # 设置页把源切成酷狗 → tick 轮询发现不一致 → 重新抓取
    cfg["lyric_source"] = "kugou"
    backend._on_tick()
    check("refetch scheduled on source change", backend.state == "loading", backend.state)
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "kugou")
    check("refetched with kugou", calls == ["auto", "kugou"], str(calls))


def test_translation_toggle_reapplies():
    cfg = {"show_translation": True}
    media = FakeMedia()

    def getter(key):
        return cfg.get(key)

    backend = LyricsBackend(media, getter, cache_dir=tempfile.mkdtemp(),
                            fetch_func=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")
    media._pos = 1500
    backend._on_tick()
    check("translation on", backend.subLine == "Sunny day")

    cfg["show_translation"] = False
    backend._on_tick()
    check("translation off reapplied immediately",
          backend.subLine == "词 周杰伦" and not backend.subIsTranslation,
          f"{backend.subLine!r}")


def test_json_roundtrip():
    doc = make_doc()
    data = doc_to_json(doc)
    back = doc_from_json(data)
    check("json roundtrip lines", len(back.lines) == len(doc.lines))
    l0 = back.lines[0]
    check("json roundtrip words",
          [(w.text, w.start_ms, w.end_ms) for w in l0.words] ==
          [(w.text, w.start_ms, w.end_ms) for w in doc.lines[0].words])
    check("json roundtrip translation", l0.translation == "Sunny day")
    check("json roundtrip source", back.source == "qqmusic")


def test_song_cleared_to_idle():
    backend, media, _ = make_backend(fetch=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    backend._do_fetch()
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")
    media._pos = 1200
    backend._on_tick()
    backend._on_song_changed("", "")  # 停止播放
    check("idle after stop", backend.state == "idle", backend.state)
    check("line cleared", backend.lineText == "" and backend.words == [])


if __name__ == "__main__":
    test_word_line_and_translation()
    test_no_translation_falls_to_next_line()
    test_line_level_doc_single_word()
    test_seek_updates_line()
    test_stale_generation_discarded()
    test_nomatch_and_error_states()
    test_cache_roundtrip_and_hit()
    test_source_change_triggers_refetch()
    test_translation_toggle_reapplies()
    test_json_roundtrip()
    test_song_cleared_to_idle()
    print()
    if fails:
        print(f"FAILED: {fails}")
        sys.exit(1)
    print("ALL PASS")
