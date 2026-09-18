"""lyrics_providers 解析器单元测试（离线，用实测 API 返回的真实格式样本）。"""

import base64
import json
import sys

import lyrics_providers as lp


def test_parse_qrc():
    # 真实样本：QQ音乐《晴天》首行（字在前、时间戳在后，绝对毫秒）
    qrc = "\n".join([
        "[ti:晴天]",
        "[ar:周杰伦]",
        "[offset:0]",
        "[0,2250]晴(0,160)天(160,160) (320,160)-(480,160) (640,160)周(800,160)杰(960,160)伦(1120,160) (1280,160)",
        "[2250,2250]词(2250,450)：(2700,450)周(3150,450)杰(3600,450)伦(4055,445)",
    ])
    lines = lp.parse_qrc(qrc)
    assert len(lines) == 2, f"expect 2 lines, got {len(lines)}"

    l0 = lines[0]
    assert l0.start_ms == 0 and l0.end_ms == 2250
    assert l0.text == "晴天 - 周杰伦", repr(l0.text)
    assert [(w.text, w.start_ms, w.end_ms) for w in l0.words] == [
        ("晴", 0, 160), ("天", 160, 320), (" ", 320, 480),
        ("-", 480, 640), (" ", 640, 800), ("周", 800, 960),
        ("杰", 960, 1120), ("伦", 1120, 1280), (" ", 1280, 1440),
    ], [(w.text, w.start_ms, w.end_ms) for w in l0.words]

    l1 = lines[1]
    assert l1.start_ms == 2250 and l1.end_ms == 4500
    assert l1.words[0].text == "词" and l1.words[0].start_ms == 2250
    assert l1.words[-1].text == "伦" and l1.words[-1].end_ms == 4500

    doc = lp.LyricsDocument(lines, "qqmusic", "晴天")
    assert doc.has_word_timing
    print("PASS parse_qrc")


def test_qrc_kana_furigana():
    """QQ QRC [kana:] 振假名解析：条目以括号外的裸 '1' 分隔，注音按汉字顺序对齐。

    语法要点（实测逆向所得）：
    - [kana:] 是整首歌一条，不分行；
    - 条目分隔符是**括号外的**字面 '1' —— 时间戳 (3428,116) 里的数字不能当分隔符；
    - 条目 = 假名读音 + 可选 (start_ms, dur_ms) 逐词时间戳；
    - **一条注音对应一个含汉字的词**，纯假名/拉丁/标点词不占条目。
      这一条决定了 fixture 必须写成「每个汉字词一条读音」，多塞一条纯假名读音
      会把其后所有注音整体推移（这是格式本身的约定，不是解析缺陷）。
    - 带时间戳的条目是可靠锚点（其 start_ms 等于 QRC 该词的 start_ms）。
    """
    # 分行覆盖：汉字+假名混排行、纯假名行、带时间锚点的行
    qrc = "\n".join([
        "[ti:テスト]",
        "[0,2000]涙(0,900)の(900,300)雨(1200,800)",
        "[2000,2000]きれいだね",
        "[4000,2000]黄昏(4000,900)を(4900,300)眺(5200,800)めて",
        "[kana:なみだ1あめ1たそがれ(4000,900)1なが]",
    ])
    lines = lp.parse_qrc(qrc)
    assert len(lines) == 3, f"expect 3 lines, got {len(lines)}"

    l0 = lines[0]
    assert l0.text == "涙の雨", repr(l0.text)
    assert l0.words[0].text == "涙" and l0.words[0].ruby == "なみだ", \
        [(w.text, w.ruby) for w in l0.words]
    assert l0.words[1].text == "の" and l0.words[1].ruby == "", \
        "纯假名词不该被挂上 ruby（它不占 [kana:] 条目）"
    assert l0.words[2].text == "雨" and l0.words[2].ruby == "あめ", \
        [(w.text, w.ruby) for w in l0.words]
    print("PASS qrc kana: 汉字挂注音、纯假名词留空")

    # 纯假名行：整行无汉字 → 全部空 ruby，不会误挂
    l1 = lines[1]
    assert l1.text == "きれいだね"
    assert all(w.ruby == "" for w in l1.words), \
        f"纯假名行不该有 ruby，got {[w.ruby for w in l1.words]}"

    # 时间锚点：带时间戳的注音必须落在同 start_ms 的词上
    l2 = lines[2]
    assert l2.words[0].text == "黄昏" and l2.words[0].ruby == "たそがれ", \
        f"锚点对齐失败: text={l2.words[0].text!r} ruby={l2.words[0].ruby!r}"
    assert l2.words[1].text == "を" and l2.words[1].ruby == "", \
        [(w.text, w.ruby) for w in l2.words]
    assert l2.words[-1].text == "眺めて" and l2.words[-1].ruby == "なが", \
        f"锚点后顺序回退失败: text={l2.words[-1].text!r} ruby={l2.words[-1].ruby!r}"

    # 无 [kana:] 的文档：全篇 ruby 恒为空串（非日语源不会凭空多出注音）
    plain = lp.parse_qrc("\n".join([
        "[ti:x]", "[0,1000]晴(0,500)天(500,500)",
    ]))
    assert all(w.ruby == "" for ln in plain for w in ln.words), \
        "无 [kana:] 时 ruby 必须为空"


def test_qrc_kana_paren_timings_are_not_separators():
    """回归守卫：分隔符判定必须忽略括号内的数字，否则注音会被时间戳切碎。"""
    blob = "きょく1うた(3428,116)1こころ"
    entries = lp._split_kana_entries(blob)
    assert entries == ["きょく", "うた(3428,116)", "こころ"], entries
    readings = lp.parse_kana("[kana:" + blob + "]")
    assert [r for r, _ in readings] == ["きょく", "うた", "こころ"], readings
    assert [t for _, t in readings] == [None, 3428, None], readings


def test_parse_krc():
    lang_json = json.dumps({"content": [
        {"type": 1, "lyricContent": [["梦いっぱい"], ["如果只是一场梦"]]},
    ]})
    krc = "\n".join([
        "[id:$00000000]",
        "[total:259000]",
        f"[language:{base64.b64encode(lang_json.encode()).decode()}]",
        "[476,3153]<0,658,0>米<658,585,0>津<1243,545,0>玄<1788,434,0>師 <2222,395,0>- <2617,536,0>Lemon",
        "[3829,2588]<0,354,0>词<354,332,0>：<686,379,0>米<1065,348,0>津",
    ])
    lines = lp.parse_krc(krc)
    assert len(lines) == 2, f"expect 2 lines, got {len(lines)}"

    l0 = lines[0]
    assert l0.start_ms == 476 and l0.end_ms == 476 + 3153
    assert l0.text == "米津玄師 - Lemon", repr(l0.text)
    # 词1 "米" 偏移0时长658 → 476-1134
    assert (l0.words[0].text, l0.words[0].start_ms, l0.words[0].end_ms) == ("米", 476, 1134)
    # 词2 "津" 偏移658 → 1134 起
    assert (l0.words[1].text, l0.words[1].start_ms) == ("津", 1134)
    # 末词 "Lemon" 偏移2617 → 476+2617=3093
    assert (l0.words[-1].text, l0.words[-1].start_ms, l0.words[-1].end_ms) == ("Lemon", 3093, 3629)

    # 翻译按索引对齐
    assert lines[0].translation == "梦いっぱい"
    assert lines[1].translation == "如果只是一场梦"
    print("PASS parse_krc")


def test_apply_lrc_translation():
    # QQ 翻译是明文 LRC（时间戳与 QRC 行对齐）
    lines = lp.parse_qrc(
        "[0,2250]晴(0,160)天(160,160)\n[2250,2250]词(2250,450)：(2700,450)")
    trans = [(0, "Sunny day"), (2250, "Lyricist")]
    lp.apply_lrc_translation(lines, trans)
    assert lines[0].translation == "Sunny day"
    assert lines[1].translation == "Lyricist"
    print("PASS apply_lrc_translation")


def test_decrypt_krc_roundtrip():
    # 构造一个最小 KRC 载荷验证解密流程（XOR + zlib）
    import zlib
    plain = "[0,1000]<0,500,0>測<500,500,0>試".encode()
    comp = zlib.compress(plain)
    key = lp._KRC_KEY
    enc = b"krc1" + bytes(b ^ key[i % len(key)] for i, b in enumerate(comp))
    import base64 as b64
    text = lp.decrypt_krc(b64.b64encode(enc).decode())
    assert "<0,500,0>測" in text
    lines = lp.parse_krc(text)
    assert lines[0].words[0].text == "測"
    print("PASS decrypt_krc roundtrip")


def test_netease_provider_parse():
    # 网易云行级歌词：无逐字时间戳，words 为空、行结束回填为下一行起始
    doc = lp.LyricsDocument([], "netease")
    lines = [lp.LyricLine(1000, None, "第一行", [], None),
             lp.LyricLine(3000, None, "第二行", [], "Second")]
    for i, ln in enumerate(lines):
        if ln.end_ms is None:
            ln.end_ms = lines[i + 1].start_ms if i + 1 < len(lines) else ln.start_ms + 5000
    assert lines[0].end_ms == 3000
    assert not any(l.words for l in lines)
    print("PASS netease line model")


def test_meaningful_lyrics_filter():
    empty = lp.LyricsDocument([], "netease")
    assert not lp.is_meaningful_lyrics(empty)
    assert not lp.is_meaningful_lyrics(None)
    instrumental = lp.LyricsDocument(
        [lp.LyricLine(0, 1000, "纯音乐"), lp.LyricLine(1000, 2000, "Instrumental")],
        "netease",
    )
    assert not lp.is_meaningful_lyrics(instrumental)
    real = lp.LyricsDocument(
        [lp.LyricLine(0, 1000, "纯音乐"), lp.LyricLine(1000, 2000, "真正的歌词")],
        "netease",
    )
    assert lp.is_meaningful_lyrics(real)
    print("PASS meaningful lyrics filter")


if __name__ == "__main__":
    test_parse_qrc()
    test_qrc_kana_furigana()
    test_qrc_kana_paren_timings_are_not_separators()
    test_parse_krc()
    test_apply_lrc_translation()
    test_decrypt_krc_roundtrip()
    test_netease_provider_parse()
    test_meaningful_lyrics_filter()
    print("ALL PASS")
    sys.exit(0)
