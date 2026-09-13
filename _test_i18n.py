"""i18n 测试：语言映射规则 + 各翻译目录 .qm 可加载且译文正确。

翻译源语言为简体中文；CW2 语言（QLocale.name() 格式）经
main._catalog_for_language 映射到 i18n/MediaWidgets_<catalog>.qm。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtGui import QGuiApplication

app = QGuiApplication(sys.argv)

import main as plugin_main

fails = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        fails.append(name)


# ---- 1. 语言映射 ----

cases = {
    "zh_CN": "zh_CN", "zh_SG": "zh_CN", "zh": "zh_CN", "zh_SIMPLIFIED": "zh_CN",
    "zh_HK": "zh_TW", "zh_TW": "zh_TW", "zh_MO": "zh_TW", "lzh": "zh_TW",
    "ja_JP": "ja_JP", "ja": "ja_JP",
    "en_US": "en_US", "en_GB": "en_US", "en": "en_US",
    "fr_FR": "en_US", "it": "en_US", "ta": "en_US", "": "en_US",
}
bad = {k: plugin_main._catalog_for_language(k) for k, v in cases.items()
       if plugin_main._catalog_for_language(k) != v}
check("language mapping", not bad, f"mismatch: {bad}")

# ---- 2. .qm 目录加载与译文抽查 ----

I18N = Path(plugin_main._I18N_DIR)

def translated(catalog, context, source):
    tr = QTranslator()
    qm = I18N / f"MediaWidgets_{catalog}.qm"
    if not tr.load(str(qm)):
        return None
    return tr.translate(context, source)


samples = {
    "en_US": [("MediaWidgetsSettings", "正在播放", "Now Playing"),
               ("MediaWidgetsSettings", "显示播放源图标", "Show Source App Icon"),
               ("MediaWidgetsSettings", "小组件自定义", "Customize Widgets"),
               ("MediaWidgetsSettings", "显示翻译，如没有就显示第二行歌词",
                "Show translation; show the next lyric if unavailable"),
               ("MediaWidgetsSettings", "原文歌词字体", "Original Lyrics Font"),
               ("MediaWidgetsSettings", "罗马音歌词字体", "Romanized Lyrics Font"),
               ("MediaWidgetsSettings", "字重", "Weight"),
               ("LyricsWidget", "跟随全局字体", "Follow Global Font"),
               ("MediaWidget", "Playing", "Playing"),
               ("LyricsWidget", "正在获取歌词…", "Fetching lyrics…")],
    "zh_TW": [("MediaWidgetsSettings", "正在播放", "正在播放"),
               ("MediaWidgetsSettings", "显示播放源图标", "顯示播放來源圖示"),
               ("MediaWidgetsSettings", "渐变背景", "漸層背景"),
               ("MediaWidgetsSettings", "字体", "字型"),
               ("MediaWidgetsSettings", "跟随全局字体", "跟隨全域字型"),
               ("MediaWidget", "Media", "媒體"),
               ("LyricsWidget", "歌词获取失败", "歌詞取得失敗")],
    "ja_JP": [("MediaWidgetsSettings", "正在播放", "再生中"),
               ("MediaWidgetsSettings", "显示播放源图标", "再生元アイコンを表示"),
               ("MediaWidgetsSettings", "副行内容", "サブ行の内容"),
               ("MediaWidgetsSettings", "字体", "フォント"),
               ("MediaWidgetsSettings", "罗马音歌词字体", "ローマ字歌詞のフォント"),
               ("MediaWidget", "Media", "メディア")],
    "zh_CN": [("MediaWidgetsSettings", "正在播放", "正在播放"),
               ("MediaWidgetsSettings", "歌词组件", "歌词组件"),
               ("MediaWidgetsSettings", "原文歌词字体", "原文歌词字体"),
               ("MediaWidget", "Media", "媒体"),
              ("MediaWidget", "Playing", "播放中")],
}

for catalog, items in samples.items():
    for context, source, expect in items:
        got = translated(catalog, context, source)
        check(f"{catalog}: {source!r}", got == expect, f"got {got!r}")

# 每份目录 52 条，且 .ts 里没有遗留的 unfinished（lrelease 时无遗漏）
for catalog in ("en_US", "zh_CN", "zh_TW", "ja_JP"):
    qm = I18N / f"MediaWidgets_{catalog}.qm"
    check(f"{catalog}.qm exists", qm.exists())
    ts_text = (I18N / f"MediaWidgets_{catalog}.ts").read_text(encoding="utf-8")
    unfinished = ts_text.count('type="unfinished"')
    check(f"{catalog}.ts fully translated", unfinished == 0,
          f"{unfinished} unfinished")
    check(f"{catalog}.ts has 52 messages", ts_text.count("<source>") == 52,
          f"{ts_text.count('<source>')} messages")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
