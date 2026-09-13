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
    """两行逐字歌词：第一行带翻译，第二行无翻译。

    结束时间取「词级末点 / 下一行之前的真实空档」，与真实抓取结果一致
    （行结束早于行起点会让间奏判定看到假空档）。
    """
    return lp.LyricsDocument([
        lp.LyricLine(1000, 4000, "晴天 周杰伦",
                     [lp.LyricWord(1000, 1600, "晴天"),
                      lp.LyricWord(1600, 2600, " "),
                      lp.LyricWord(2600, 3800, "周杰伦")],
                     translation="Sunny day"),
        lp.LyricLine(5000, 8000, "词 周杰伦",
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
    check("intro word timing on", backend.wordTiming is True)
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


def test_subtitle_modes():
    backend, media, _ = make_backend(config={"lyric_subtitle_content": "next"},
                                     fetch=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")

    # 第一行有翻译但选择下一行 → 下一行预览
    media._pos = 1500
    backend._on_tick()
    check("next mode -> next line",
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
    """行级歌词（网易云 LRC）→ 整行一个 word，但 wordTiming=False（不走卡拉OK）。"""
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
    check("line-level has no word timing", backend.wordTiming is False)
    # 第一行无翻译 → 下一行预览
    check("line-level next-line preview", backend.subLine == "第二行", backend.subLine)
    media._pos = 5000
    backend._on_tick()
    check("line-level sub translation", backend.subLine == "Line 2", backend.subLine)


def test_word_timing_flag_for_qrc():
    """逐字行 wordTiming=True，供 QML 开启卡拉OK填充。"""
    backend, media, _ = make_backend(fetch=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")
    media._pos = 1200
    backend._on_tick()
    check("word-level timing enabled", backend.wordTiming is True)
    check("word-level has multiple words", len(backend.words) >= 2, str(backend.words))


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


def test_subtitle_mode_reapplies():
    cfg = {"lyric_subtitle_content": "translation_or_next"}
    media = FakeMedia()

    def getter(key):
        return cfg.get(key)

    backend = LyricsBackend(media, getter, cache_dir=tempfile.mkdtemp(),
                            fetch_func=lambda *a: (make_doc(), "qqmusic"))
    backend._on_song_changed("晴天", "周杰伦")
    backend._fetch_worker(backend._gen, "晴天", "周杰伦", media.duration_ms, "auto")
    media._pos = 1500
    backend._on_tick()
    check("translation-or-next shows translation", backend.subLine == "Sunny day")

    cfg["lyric_subtitle_content"] = "translation_or_none"
    backend._on_tick()
    check("translation-or-none keeps translation when available",
          backend.subLine == "Sunny day" and backend.subIsTranslation,
          f"{backend.subLine!r}")

    # 切到下一行：有翻译时也不使用翻译；切到不显示时完全隐藏副行。
    cfg["lyric_subtitle_content"] = "next"
    backend._on_tick()
    check("next mode reapplied immediately",
          backend.subLine == "词 周杰伦" and not backend.subIsTranslation,
          f"{backend.subLine!r}")
    cfg["lyric_subtitle_content"] = "none"
    backend._on_tick()
    check("none mode reapplied immediately",
          backend.subLine == "" and not backend.subIsTranslation,
          f"{backend.subLine!r}")

    # translation-or-none 在无翻译行不回退到下一行。
    cfg["lyric_subtitle_content"] = "translation_or_none"
    media._pos = 5500
    backend._on_tick()
    check("translation-or-none does not fall back",
          backend.subLine == "" and not backend.subIsTranslation,
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


def test_instrumental_document_is_nomatch():
    """纯音乐占位行视为无可用歌词，进入 nomatch 以便组件自动隐藏。"""
    instrumental = lp.LyricsDocument(
        [lp.LyricLine(0, 5000, "纯音乐", [], None)],
        "netease",
        "Theme",
    )
    backend, media, _ = make_backend(fetch=lambda *a: (instrumental, "netease"))
    backend._on_song_changed("Theme", "Artist")
    backend._fetch_worker(backend._gen, "Theme", "Artist", media.duration_ms, "auto")
    check("instrumental → nomatch", backend.state == "nomatch", backend.state)
    check("instrumental clears line", backend.lineText == "" and backend.words == [])


def make_interlude_doc():
    """逐字歌词：第三行之前有 8s 长空档 → 应判为间奏。"""
    def line(start, end, text):
        return lp.LyricLine(start, end, text, [lp.LyricWord(start, end, text)], None)
    return lp.LyricsDocument([
        line(1000, 3000, "第一句"),
        line(4000, 6000, "第二句"),
        line(14000, 16000, "第三句"),
    ], "qqmusic", "间奏测试")


def test_interlude_detected_on_long_gap():
    backend, media, _ = make_backend(fetch=lambda *a: (make_interlude_doc(), "qqmusic"))
    backend._on_song_changed("间奏测试", "艺")
    backend._fetch_worker(backend._gen, "间奏测试", "艺", media.duration_ms, "auto")
    check("interlude off while lyrics playing", not backend.interlude)
    media._pos = 5000
    backend._on_tick()
    check("still normal line mid-song", not backend.interlude and backend.lineText == "第二句",
          f"{backend.interlude} {backend.lineText!r}")

    # 第二句结束（6000）即进入间奏；终点 = 第三句起点 - 250ms 提前量
    media._pos = 6000
    backend._on_tick()
    check("interlude starts when previous line ends", backend.interlude, str(backend.interlude))
    check("interlude start ms", backend.interludeStartMs == 6000, backend.interludeStartMs)
    check("interlude end ms subtracts lead-in", backend.interludeEndMs == 13750,
          backend.interludeEndMs)
    check("interlude clears lyrics line", backend.lineText == "" and backend.words == [],
          f"{backend.lineText!r} {backend.words!r}")

    media._pos = 10000
    backend._on_tick()
    check("interlude holds across mid-gap", backend.interlude and backend.lineText == "")

    # 提前量窗口 [gap[1], 下一行起点)：直接预显示下一句（未填充），不回落上一句
    media._pos = 13800
    backend._on_tick()
    check("lead-in window pre-shows next line",
          not backend.interlude and backend.lineText == "第三句",
          f"{backend.interlude} {backend.lineText!r}")

    media._pos = 14100
    backend._on_tick()
    check("next line takes over after interlude",
          not backend.interlude and backend.lineText == "第三句")


def test_short_gap_is_not_interlude():
    """空档 < 4s 属普通换行，不切呼吸点（避免逐句之间频繁闪烁）。"""
    doc = lp.LyricsDocument([
        lp.LyricLine(0, 2000, "甲", [lp.LyricWord(0, 2000, "甲")], None),
        lp.LyricLine(5000, 7000, "乙", [lp.LyricWord(5000, 7000, "乙")], None),
    ], "qqmusic", "短空档")
    backend, media, _ = make_backend(fetch=lambda *a: (doc, "qqmusic"))
    backend._on_song_changed("短空档", "艺")
    backend._fetch_worker(backend._gen, "短空档", "艺", media.duration_ms, "auto")
    media._pos = 3500  # 2000 → 4750 只有 2750ms
    backend._on_tick()
    check("2.75s gap is not interlude", not backend.interlude, str(backend.interlude))


def test_intro_gap_becomes_interlude():
    """首行开始前的长前奏同样算间奏，起点为 0。"""
    doc = lp.LyricsDocument([
        lp.LyricLine(12000, 14000, "第一句", [lp.LyricWord(12000, 14000, "第一句")], None),
        lp.LyricLine(16000, 18000, "第二句", [lp.LyricWord(16000, 18000, "第二句")], None),
    ], "qqmusic", "长前奏")
    backend, media, _ = make_backend(fetch=lambda *a: (doc, "qqmusic"))
    backend._on_song_changed("长前奏", "艺")
    backend._fetch_worker(backend._gen, "长前奏", "艺", media.duration_ms, "auto")
    media._pos = 3000
    backend._on_tick()
    check("intro gap becomes interlude", backend.interlude, str(backend.interlude))
    check("intro interlude starts at 0", backend.interludeStartMs == 0,
          backend.interludeStartMs)
    check("intro interlude clears line", backend.lineText == "", repr(backend.lineText))

    media._pos = 11900  # 提前量窗口
    backend._on_tick()
    check("intro lead-in pre-shows first line",
          not backend.interlude and backend.lineText == "第一句",
          f"{backend.interlude} {backend.lineText!r}")


def test_line_level_lyrics_never_interlude():
    """行级歌词以「下一行起点」为行结束 → 不存在空档，绝不误判间奏。"""
    doc = lp.LyricsDocument([
        lp.LyricLine(0, 5000, "第一行", [], None),
        lp.LyricLine(5000, 12000, "第二行", [], None),
        lp.LyricLine(12000, 20000, "第三行", [], None),
    ], "netease", "行级")
    backend, media, _ = make_backend(fetch=lambda *a: (doc, "netease"))
    backend._on_song_changed("行级", "艺")
    backend._fetch_worker(backend._gen, "行级", "艺", media.duration_ms, "auto")
    bad = None
    for pos in (0, 3000, 5100, 9000, 13000):
        media._pos = pos
        backend._on_tick()
        if backend.interlude:
            bad = pos
            break
    check("line-level lyrics never produce interlude", bad is None, f"triggered at {bad}")


def test_song_change_and_nomatch_clear_interlude():
    backend, media, _ = make_backend(fetch=lambda *a: (make_interlude_doc(), "qqmusic"))
    backend._on_song_changed("间奏测试", "艺")
    backend._fetch_worker(backend._gen, "间奏测试", "艺", media.duration_ms, "auto")
    media._pos = 10000
    backend._on_tick()
    check("interlude active before song change", backend.interlude)
    backend._on_song_changed("另一首", "艺")
    check("interlude reset on song change",
          not backend.interlude and backend.interludeStartMs == 0
          and backend.interludeEndMs == 0,
          f"{backend.interlude} {backend.interludeStartMs} {backend.interludeEndMs}")

    backend2, media2, _ = make_backend(fetch=lambda *a: (None, None))
    backend2._on_song_changed("无", "歌")
    backend2._fetch_worker(backend2._gen, "无", "歌", media2.duration_ms, "auto")
    check("interlude off in nomatch", not backend2.interlude and backend2.interludeEndMs == 0)


if __name__ == "__main__":
    test_word_line_and_translation()
    test_subtitle_modes()
    test_line_level_doc_single_word()
    test_word_timing_flag_for_qrc()
    test_seek_updates_line()
    test_stale_generation_discarded()
    test_nomatch_and_error_states()
    test_cache_roundtrip_and_hit()
    test_source_change_triggers_refetch()
    test_subtitle_mode_reapplies()
    test_json_roundtrip()
    test_song_cleared_to_idle()
    test_instrumental_document_is_nomatch()
    test_interlude_detected_on_long_gap()
    test_short_gap_is_not_interlude()
    test_intro_gap_becomes_interlude()
    test_line_level_lyrics_never_interlude()
    test_song_change_and_nomatch_clear_interlude()
    print()
    if fails:
        print(f"FAILED: {fails}")
        sys.exit(1)
    print("ALL PASS")
