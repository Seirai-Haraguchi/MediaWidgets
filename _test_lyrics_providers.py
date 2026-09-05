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


def test_parse_krc():
    # 真实样本：酷狗《Lemon》首行（时间戳在前、字在后，相对行首偏移）
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


if __name__ == "__main__":
    test_parse_qrc()
    test_parse_krc()
    test_apply_lrc_translation()
    test_decrypt_krc_roundtrip()
    test_netease_provider_parse()
    print("ALL PASS")
    sys.exit(0)
