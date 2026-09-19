"""开发用冒烟测试：独立 QML 引擎加载歌词组件，验证语法 / 属性 / 逐字渲染。

不依赖 CW2 运行时：Widget 与 Theme 用最小桩模块模拟（ClassWidgets.Theme），
AppCentral / Utils / Configs / backend 用 Python 桩注入。
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression

app = QGuiApplication(sys.argv)

PLUGIN_DIR = Path(__file__).parent

# 桩模块临时目录放项目内：系统盘满时（CI/本地）不再阻塞测试
STUB_TMP_DIR = PLUGIN_DIR / ".tmp"


# ---- ClassWidgets.Theme 桩模块 ----

def build_stub_module():
    """构造可被 import ClassWidgets.Theme 解析的最小模块目录。

    只桩组件类型（Widget/Title/MarqueeTitle），接口与 CW2 真实组件一致；
    Theme/Utils 不在这里桩 —— 它们是 RinUI 单例，组件经 `import RinUI as Rin`
    访问，由 build_stub_rinui 提供同名桩模块。
    """
    STUB_TMP_DIR.mkdir(parents=True, exist_ok=True)
    mod_dir = Path(tempfile.mkdtemp(prefix="cw_theme_stub_", dir=STUB_TMP_DIR)) / "ClassWidgets" / "Theme"
    mod_dir.mkdir(parents=True)
    (mod_dir / "qmldir").write_text(
        "module ClassWidgets.Theme\n"
        "Widget 2.0 Widget.qml\n"
        "Title 2.0 Title.qml\n"
        "MarqueeTitle 2.0 MarqueeTitle.qml\n",
        encoding="utf-8")
    (mod_dir / "Widget.qml").write_text(
        "import QtQuick\n"
        "Item {\n"
        "    id: widgetBase\n"
        "    property string text: ''\n"
        "    property bool miniMode: false\n"
        "    property bool editMode: false\n"
        "    property var backend: null\n"
        "    property real cornerRadius: height * 0.22\n"
        "    property real padding: miniMode ? 16 : 24\n"
        "    property alias backgroundArea: backgroundArea.children\n"
        "    default property alias content: contentArea.data\n"
        "    implicitWidth: 260\n"
        "    height: miniMode ? 56 : 100\n"
        "    // 与 CW2 真实 Widget 同款卡片底：圆角矩形 + 渐变描边\n"
        "    Rectangle {\n"
        "        anchors.fill: parent\n"
        "        radius: height * 0.22\n"
        "        color: Qt.rgba(0.98, 0.98, 1.0, 0.7)\n"
        "        border.width: 1.5\n"
        "        border.color: Qt.rgba(1, 1, 1, 0.9)\n"
        "    }\n"
        "    Item { id: backgroundArea; anchors.fill: parent }\n"
        "    Item { id: contentArea; anchors.fill: parent }\n"
        "}\n",
        encoding="utf-8")
    (mod_dir / "Title.qml").write_text(
        "import QtQuick\n"
        "Text {}\n",
        encoding="utf-8")
    (mod_dir / "MarqueeTitle.qml").write_text(
        "import QtQuick\n"
        "Item {\n"
        "    property alias text: label.text\n"
        "    property alias color: label.color\n"
        "    property alias font: label.font\n"
        "    property int maximumWidth: 200\n"
        "    property int speed: 50\n"
        "    implicitWidth: Math.min(label.implicitWidth, maximumWidth)\n"
        "    implicitHeight: label.implicitHeight\n"
        "    clip: true\n"
        "    Text { id: label; anchors.verticalCenter: parent.verticalCenter }\n"
        "}\n",
        encoding="utf-8")
    return mod_dir.parent.parent


def build_stub_rinui():
    """构造可被 import RinUI 解析的最小桩模块（只含组件用到的 Theme/Utils 单例）。

    不能让测试引擎实例化 venv 里的真实 RinUI 单例：裸引擎（无 ThemeManager、
    无 RinUIWindow 的应用级初始化）下实例化真实 Theme/Utils 会让之后创建的
    QQuickText 宽度全部测为 0（真实 CW2 运行时由框架先完成初始化，无此问题，
    见 CW2 自身组件与 MediaWidget 的线上表现）。
    """
    mod_dir = Path(tempfile.mkdtemp(prefix="rinui_stub_", dir=STUB_TMP_DIR)) / "RinUI"
    mod_dir.mkdir(parents=True)
    (mod_dir / "qmldir").write_text(
        "module RinUI\n"
        "singleton Theme 2.0 Theme.qml\n"
        "singleton Utils 2.0 Utils.qml\n",
        encoding="utf-8")
    (mod_dir / "Theme.qml").write_text(
        "pragma Singleton\n"
        "import QtQuick\n"
        "QtObject {\n"
        "    function isDark() { return false }\n"
        "}\n",
        encoding="utf-8")
    (mod_dir / "Utils.qml").write_text(
        "pragma Singleton\n"
        "import QtQuick\n"
        "QtObject {\n"
        "    property string fontFamily: \"Microsoft YaHei\"\n"
        "}\n",
        encoding="utf-8")
    return mod_dir.parent


# ---- Python 桩：媒体后端 / 歌词后端 / 环境单例 ----

class StubMedia(QObject):
    titleChanged = Signal()
    artistChanged = Signal()
    artChanged = Signal()
    progressChanged = Signal()
    playingChanged = Signal()
    accentColorChanged = Signal()

    @Property(str, notify=titleChanged)
    def title(self):
        return "晴天"

    @Property(str, notify=artistChanged)
    def artist(self):
        return "周杰伦"

    @Property(str, notify=artChanged)
    def art(self):
        return "data:image/png;base64,AAAA"

    @Property(float, notify=progressChanged)
    def progress(self):
        return 0.42

    @Property(str, notify=progressChanged)
    def positionText(self):
        return "1:23"

    @Property(str, notify=progressChanged)
    def durationText(self):
        return "4:29"

    @Property(str, notify=accentColorChanged)
    def accentColor(self):
        return "#7C4DFF"

    @Property(str, notify=accentColorChanged)
    def accentColor2(self):
        return "#4DB6AC"

    @Property(bool, notify=playingChanged)
    def isPlaying(self):
        return True


class StubLyricsBackend(QObject):
    stateChanged = Signal()
    lineChanged = Signal()
    positionChanged = Signal()
    sourceNameChanged = Signal()
    interludeChanged = Signal()

    def __init__(self, media, parent=None):
        super().__init__(parent)
        self._media = media
        self._state = "ready"
        self._words = [
            {"text": "晴天", "startMs": 1000, "endMs": 1600},
            {"text": " ", "startMs": 1600, "endMs": 2600},
            {"text": "周杰伦", "startMs": 2600, "endMs": 3800},
        ]
        self._word_timing = True
        self._line_is_japanese = False
        self._sub_line = "Sunny day"
        self._position_ms = 1300
        self._interlude = False
        self._interlude_start_ms = 0
        self._interlude_end_ms = 0

    @Property(QObject, constant=True)
    def media(self):
        return self._media

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Slot(str)
    def set_state(self, state):
        self._state = state
        self.stateChanged.emit()

    @Property(str, notify=lineChanged)
    def lineText(self):
        return "晴天 周杰伦"

    @Property("QVariantList", notify=lineChanged)
    def words(self):
        return self._words

    @Property(bool, notify=lineChanged)
    def wordTiming(self):
        return self._word_timing

    @Property(bool, notify=lineChanged)
    def lineIsJapanese(self):
        return self._line_is_japanese

    @Property(str, notify=lineChanged)
    def subLine(self):
        return self._sub_line

    @Property(bool, notify=lineChanged)
    def subIsTranslation(self):
        return True

    @Property(int, notify=positionChanged)
    def positionMs(self):
        return self._position_ms

    @Slot(int)
    def set_position(self, ms):
        self._position_ms = ms
        self.positionChanged.emit()

    def set_line(self, words, word_timing=True, sub_line="", japanese=None):
        self._words = words
        self._word_timing = word_timing
        self._sub_line = sub_line
        if japanese is not None:
            self._line_is_japanese = japanese
        self.lineChanged.emit()

    @Property(bool, notify=interludeChanged)
    def interlude(self):
        return self._interlude

    @Property(int, notify=interludeChanged)
    def interludeStartMs(self):
        return self._interlude_start_ms

    @Property(int, notify=interludeChanged)
    def interludeEndMs(self):
        return self._interlude_end_ms

    def set_interlude(self, active, start_ms=0, end_ms=0):
        self._interlude = active
        self._interlude_start_ms = start_ms
        self._interlude_end_ms = end_ms
        self.interludeChanged.emit()

    @Property(str, notify=sourceNameChanged)
    def sourceName(self):
        return "QQ音乐"


class StubAppCentral(QObject):
    @Slot(str, str, result=QFont)
    def getQFont(self, family, fallback):
        return QFont(family or fallback or "Arial")


class StubConfigs(QObject):
    configChanged = Signal()

    def __init__(self):
        super().__init__()
        self._prefs = {
            "lyric_source": "auto",
            "lyric_gradient_background": True,
            "lyric_gradient_intensity": 100,
            "lyric_subtitle_content": "translation_or_next",
            "lyric_furigana_enabled": True,
            "lyric_animation_enabled": True,
        }

    def set_pref(self, key, value):
        self._prefs[key] = value
        self.configChanged.emit()

    @Property("QVariant", notify=configChanged)
    def data(self):
        return {
            "preferences": {"font": "", "font_weight": 600, "mini_mode": False},
            "plugins": {"configs": {
                "com.seiraiharaguchi.mediawidgets": dict(self._prefs)}},
        }


def main():
    engine = QQmlEngine()
    # RinUI 桩必须在真实 site-packages 之前加入导入路径，保证 import RinUI 解析到桩
    engine.addImportPath(str(build_stub_rinui()))
    engine.addImportPath(str(build_stub_module()))

    media = StubMedia()
    backend = StubLyricsBackend(media)
    # 桩对象必须持有引用：内联实例会被 Python GC 回收，上下文属性随之变空
    app_central = StubAppCentral()
    configs = StubConfigs()
    engine.rootContext().setContextProperty("AppCentral", app_central)
    engine.rootContext().setContextProperty("Configs", configs)

    problems = []
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType

    def handler(msg_type, context, message):
        if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            problems.append(message)

    qInstallMessageHandler(handler)

    url = QUrl.fromLocalFile(str(PLUGIN_DIR / "qml" / "LyricsWidget.qml"))
    component = QQmlComponent(engine, url)
    if component.status() == QQmlComponent.Status.Error:
        print("FAIL: component has errors:")
        for e in component.errors():
            print(f"  {e}")
        return 1

    root = component.create()
    if root is None:
        print("FAIL: create() returned None:")
        for e in component.errors():
            print(f"  {e}")
        return 1
    root.setProperty("backend", backend)

    # Repeater delegate は polish（レンダリング同期）で初めてレイアウトされる：
    # ウィンドウに入れて 1 フレーム描画してから検証する
    from PySide6.QtCore import QTimer, QEventLoop
    from PySide6.QtQuick import QQuickWindow
    win = QQuickWindow()
    win.resize(480, 120)
    engine.rootContext().setContextProperty("testWin", win)
    QQmlExpression(engine.rootContext(), root, "parent = testWin.contentItem").evaluate()
    root.setProperty("width", 480)
    root.setProperty("height", 120)
    win.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    assert not win.grabWindow().isNull()

    noise_patterns = (
        "theme.qml",
        "Cannot find font directory",
        "ScrollBar attached property must be attached",
    )
    page_problems = [
        p for p in problems
        if "LyricsWidget.qml" in p and not any(pat in p for pat in noise_patterns)
    ]
    for p in page_problems[:30]:
        print("QML-WARNING:", p)
    if page_problems:
        print(f"FAIL: {len(page_problems)} widget warnings")
        return 1
    print("widget: loaded without QML errors", flush=True)

    # 歌词组件的渐变背景也应当响应设置页偏好。
    gradient = next((item for item in root.findChildren(QObject)
                     if item.property("objectName") == "gradientBackground"), None)
    if gradient is None or not gradient.property("visible"):
        print("FAIL: lyrics gradient background should be visible by default")
        return 1
    configs.set_pref("lyric_gradient_intensity", 40)
    if abs(root.property("gradientIntensity") - 0.4) > 0.001:
        print(f"FAIL: lyrics gradient intensity expected 0.4, got {root.property('gradientIntensity')}")
        return 1
    configs.set_pref("lyric_gradient_background", False)
    if gradient.property("visible"):
        print("FAIL: lyrics gradient should hide when disabled")
        return 1
    print("background: lyrics gradient settings update live", flush=True)

    # 逐字 delegate 应当渲染 3 个词；词 0 已唱满（pos 1300 ≥ end 1600？否，1300<1600 → 部分）
    repeater = None
    stack = [root]
    while stack:
        item = stack.pop()
        if item.metaObject().className().startswith("QQuickRepeater"):
            repeater = item
        stack.extend(item.findChildren(QObject) or [])
    if repeater is None:
        print("FAIL: word Repeater not found")
        return 1
    count = repeater.property("count")
    if count != 3:
        print(f"FAIL: expected 3 word delegates, got {count}")
        return 1
    print(f"words: {count} delegates created", flush=True)

    # 验证词内填充比例逻辑：词0 1000-1600，pos=1300 → 0.5
    # （Repeater delegate 的 QObject parent 为 None，findChildren 扫不到，
    #   必须用 JS 表达式 itemAt(i) 取；PySide6 下树扫描永远拿不到 delegate）
    delegates = []
    for i in range(count):
        expr = QQmlExpression(engine.rootContext(), repeater, f"itemAt({i})")
        item, errored = expr.evaluate()
        if errored or item is None:
            print(f"FAIL: itemAt({i}) errored: {expr.error()}")
            return 1
        delegates.append(item)
    if len(delegates) != 3:
        print(f"FAIL: expected 3 word delegates, got {len(delegates)}")
        return 1
    delegates.sort(key=lambda d: d.property("modelData")["startMs"])
    fill = delegates[0].property("fillRatio")
    if fill is None or abs(fill - 0.5) > 0.01:
        print(f"FAIL: word0 fillRatio expected 0.5, got {fill}")
        return 1
    print(f"fill: word0 fillRatio={fill:.3f} (pos=1300 in 1000-1600)", flush=True)

    # 词1（1600-2600）与词2（2600-3800）在 pos=1300 时未开始：0
    for idx, expect in ((1, 0.0), (2, 0.0)):
        got = delegates[idx].property("fillRatio")
        if got is None or abs(got - expect) > 0.001:
            print(f"FAIL: word{idx} fillRatio expected {expect}, got {got}")
            return 1
    print("fill: unsung words stay at 0.000", flush=True)

    # 逐字填充结构：每个词 delegate = 辉光字 + 底层暗字 + clip 内顶层亮字
    # （辉光 Text 默认不可见，仅长音激活；结构上始终存在）
    # delegate 自身子项的 QObject 树正常，可用 findChildren
    def _is_text(o):
        cls = o.metaObject().className()
        return cls == "QQuickText" or cls.startswith("Text_")

    texts = [c for c in delegates[0].findChildren(QObject) if _is_text(c)]
    clips = [c for c in delegates[0].findChildren(QObject)
             if c.property("clip") is True]
    # 至少底层暗字 + clip 内亮字；辉光 Text 可能因 layer/不可见而不计入部分绑定树
    if len(texts) < 2 or len(clips) != 1:
        print(f"FAIL: word0 structure: texts={len(texts)} clips={len(clips)}")
        return 1
    clip_item = clips[0]
    top_text = next(t for t in texts if t.parent() is clip_item)
    base_text = next(
        t for t in texts
        if t.parent() is delegates[0] and t.property("text") == "晴天"
    )
    if clip_item.property("width") <= 0 or top_text.property("text") != "晴天":
        print(f"FAIL: clip width={clip_item.property('width')} top text={top_text.property('text')}")
        print(f"DEBUG: base width={base_text.property('width')} implicit={base_text.property('implicitWidth')} "
              f"px={base_text.property('font').pixelSize()} family={base_text.property('font').family()} "
              f"delegate w={delegates[0].property('width')} visible={delegates[0].property('visible')}")
        print(f"DEBUG2: base text={base_text.property('text')!r} h={base_text.property('height')}")
        p = delegates[0].parent()
        chain = []
        while p is not None:
            chain.append(f"{p.metaObject().className()}(w={p.property('width')},vis={p.property('visible')})")
            p = p.parent()
        print("DEBUG3:", " <- ".join(chain))
        return 1
    print(f"karaoke: clip width={clip_item.property('width'):.1f}px "
          f"of base {base_text.property('width'):.1f}px (texts={len(texts)})", flush=True)

    # mini 模式切回正常再渲染一次（字体/尺寸分支不炸）
    root.setProperty("miniMode", True)
    root.setProperty("miniMode", False)

    # 设计约定：歌词组件不显示封面图（专辑图）——内容区不应存在任何 Image 项
    def _is_image(o):
        return o.metaObject().className().startswith("QQuickImage")

    images = [c for c in root.findChildren(QObject) if _is_image(c)]
    if images:
        print(f"FAIL: lyrics widget should not contain album art Image, found {len(images)}")
        return 1
    print("design: no album art image in content", flush=True)

    # 跑马灯：行宽超出主行 maximumWidth（≤480）时 wordRow 向左滚
    def _find_wordrow():
        # 组合组件实例的 className 带 _QML_N 后缀，不能用精确名匹配
        stack = [root]
        while stack:
            item = stack.pop()
            cls = item.metaObject().className()
            if cls.startswith("QQuickRow") and not cls.startswith("QQuickRowLayout"):
                return item
            stack.extend(item.findChildren(QObject) or [])
        return None

    def _find_sweep():
        stack = [root]
        while stack:
            item = stack.pop()
            if item.property("wordTiming") is not None and item.property("fillEdgeX") is not None:
                return item
            stack.extend(item.findChildren(QObject) or [])
        return None

    def _wait(ms=200):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    # 超长逐字行（远超 480px），用于触发跑马灯
    long_words = [
        {"text": "这一句歌词特别特别长用来触发跑马灯滚动效果一二三四五六七八九十",
         "startMs": 0, "endMs": 8000},
        {"text": "续上后半句还要更长一些ABCDEFGHIJKLMNOPQRSTUVWXYZ",
         "startMs": 8000, "endMs": 16000},
    ]
    backend.set_line(long_words, word_timing=True, sub_line="Sunny day")
    backend.set_position(100)
    root.setProperty("width", 560)
    _wait(250)

    word_row = _find_wordrow()
    if word_row is None:
        print("FAIL: word Row not found")
        return 1
    sweep = _find_sweep()
    if sweep is None:
        print("FAIL: WordSweep not found")
        return 1

    def _row_x():
        return float(word_row.property("x") or 0)

    row_w = float(word_row.property("implicitWidth") or 0)
    view_w = float(sweep.property("width") or 0)
    if row_w <= view_w + 1:
        print(f"FAIL: expected overflow for marquee, row={row_w:.1f} view={view_w:.1f}")
        return 1
    print(f"marquee: overflow ready row={row_w:.1f} view={view_w:.1f}", flush=True)

    # 行初：演唱边缘仍在视口左侧锚点内 → 不滚（或几乎不滚）
    backend.set_position(100)
    _wait(200)
    start_x = _row_x()
    if start_x < -2:
        print(f"FAIL: early position should not scroll yet, wordRow.x={start_x}")
        return 1
    print("marquee: early position keeps row near x=0", flush=True)

    # 行中后段：跟随演唱边缘向左滚，且不超过 maxScroll
    backend.set_position(12000)
    _wait(250)
    scroll_x = _row_x()
    max_scroll = row_w - view_w
    if scroll_x >= -1 or scroll_x < -(max_scroll + 8):
        print(f"FAIL: mid/late should scroll into range, x={scroll_x} maxScroll={max_scroll:.1f}")
        return 1
    print(f"marquee: follow-scroll x={scroll_x:.1f} (max={max_scroll:.1f})", flush=True)

    # 行尾之后 → 钳制在 maxScroll
    backend.set_position(20000)
    _wait(250)
    end_x = _row_x()
    if abs(end_x - (-max_scroll)) > 10 and abs(end_x - scroll_x) > 10:
        # 允许已在钳位附近；至少不能比上一刻明显继续往左冲
        if end_x < scroll_x - 10:
            print(f"FAIL: scroll should clamp at line end, x {scroll_x:.1f} -> {end_x:.1f}")
            return 1
    print("marquee: scroll clamps at line end", flush=True)

    # 换行到短行：瞬时归位（Behavior 关闭），不从上一行 scrollX 缓动
    backend.set_line(
        [{"text": "短", "startMs": 0, "endMs": 1000}],
        word_timing=True,
        sub_line="Sunny day",
    )
    backend.set_position(100)
    _wait(50)
    word_row = _find_wordrow()
    if abs(_row_x()) > 1.0:
        print(f"FAIL: line change should snap scroll to 0, wordRow.x={_row_x()}")
        return 1
    print("marquee: line change snaps scroll to 0", flush=True)

    # 副行关闭后主行额度回到 480，内容可横向撑开（不再被 root.width 锁死）
    sweep = _find_sweep()
    backend.set_line(
        [{"text": "这是一句足够长的歌词用来撑开组件宽度ABCDEF", "startMs": 0, "endMs": 5000}],
        word_timing=True,
        sub_line="",
    )
    backend.set_position(100)
    _wait(200)
    reserve, err_r = QQmlExpression(engine.rootContext(), sweep, "secondaryReserve").evaluate()
    max_via_expr, err_m = QQmlExpression(
        engine.rootContext(), sweep, "mainMaxWidth"
    ).evaluate()
    if err_r or reserve is None:
        print(f"FAIL: secondaryReserve missing on WordSweep: {err_r}")
        return 1
    if abs(float(reserve)) > 0.5:
        print(f"FAIL: secondary disabled should reserve 0, got {reserve}")
        return 1
    if err_m or max_via_expr is None or abs(float(max_via_expr) - 480) > 0.5:
        print(f"FAIL: secondary off → main maxWidth should be 480, got {max_via_expr} err={err_m}")
        return 1
    print("width: secondary off restores main maxWidth=480", flush=True)

    # 行级歌词：不应启用卡拉OK裁切层；fillRatio 恒为 1
    backend.set_line(
        [{"text": "行级歌词一整行", "startMs": 0, "endMs": 4000}],
        word_timing=False,
        sub_line="",
    )
    backend.set_position(1000)
    _wait(200)
    repeater = None
    stack = [root]
    while stack:
        item = stack.pop()
        if item.metaObject().className().startswith("QQuickRepeater"):
            repeater = item
        stack.extend(item.findChildren(QObject) or [])
    if repeater is None or repeater.property("count") != 1:
        print(f"FAIL: line-level should have 1 delegate, count="
              f"{repeater.property('count') if repeater else None}")
        return 1
    d0, errored = QQmlExpression(engine.rootContext(), repeater, "itemAt(0)").evaluate()
    if errored or d0 is None:
        print("FAIL: line-level itemAt(0) failed")
        return 1
    if abs(float(d0.property("fillRatio")) - 1.0) > 0.001:
        print(f"FAIL: line-level fillRatio should be 1, got {d0.property('fillRatio')}")
        return 1
    clips = [c for c in d0.findChildren(QObject) if c.property("clip") is True]
    visible_clips = [c for c in clips if c.property("visible") is True]
    if visible_clips:
        print(f"FAIL: line-level must not show karaoke clip, visible clips={len(visible_clips)}")
        return 1
    wt, _ = QQmlExpression(engine.rootContext(), sweep, "wordTiming").evaluate()
    if wt is not False:
        print(f"FAIL: sweep.wordTiming should be false for line-level, got {wt}")
        return 1
    print("karaoke: line-level lyrics skip fill sweep", flush=True)

    # 行级歌词不得启用长音辉光
    if d0.property("longNoteEligible") or d0.property("glowActive"):
        print(f"FAIL: line-level must not be glow-eligible "
              f"(eligible={d0.property('longNoteEligible')} active={d0.property('glowActive')})")
        return 1
    print("glow: line-level lyrics never glow", flush=True)

    # 长音逐字：时长 >1000ms 时应在唱段内激活辉光
    backend.set_line(
        [{"text": "长音", "startMs": 0, "endMs": 2500}],
        word_timing=True,
        sub_line="",
    )
    backend.set_position(1200)
    _wait(200)
    repeater = None
    stack = [root]
    while stack:
        item = stack.pop()
        if item.metaObject().className().startswith("QQuickRepeater"):
            repeater = item
        stack.extend(item.findChildren(QObject) or [])
    d_long, errored = QQmlExpression(engine.rootContext(), repeater, "itemAt(0)").evaluate()
    if errored or d_long is None:
        print("FAIL: long-note itemAt(0) failed")
        return 1
    if not d_long.property("longNoteEligible"):
        print("FAIL: word >1000ms should be long-note eligible")
        return 1
    if not d_long.property("glowActive") or float(d_long.property("glowLevel") or 0) <= 0.02:
        print(f"FAIL: long note mid-progress should glow, "
              f"active={d_long.property('glowActive')} level={d_long.property('glowLevel')}")
        return 1
    # 短词不触发
    backend.set_line(
        [{"text": "短", "startMs": 0, "endMs": 800}],
        word_timing=True,
        sub_line="",
    )
    backend.set_position(400)
    _wait(150)
    d_short, _ = QQmlExpression(engine.rootContext(), repeater, "itemAt(0)").evaluate()
    if d_short and (d_short.property("longNoteEligible") or d_short.property("glowActive")):
        print("FAIL: word ≤1000ms must not glow")
        return 1
    print("glow: long-note glow activates only for word-timed notes >1000ms", flush=True)

    # 间奏：主行让位给三个呼吸点，两者不同时出现（避免叠字/换行跳变）
    backend.set_line([{"text": "间奏前", "startMs": 0, "endMs": 4000}],
                     word_timing=False, sub_line="")
    backend.set_position(6000)
    backend.set_interlude(True, 4000, 9750)
    _wait(150)
    if not root.property("interludeActive"):
        print("FAIL: interlude should activate while a long gap is playing")
        return 1
    if _find_sweep().property("visible"):
        print("FAIL: lyrics row must hide during interlude (dots take its place)")
        return 1
    dots_item = next((o for o in root.findChildren(QObject)
                      if o.property("objectName") == "interludeDots"), None)
    if dots_item is None:
        print("FAIL: interludeDots not found by objectName")
        return 1
    if not dots_item.property("visible"):
        print("FAIL: interlude dots should be visible during interlude")
        return 1
    # Repeater delegate 的 QObject parent 为 None，树扫描取不到：必须用 itemAt(i)
    dot_repeater = next((c for c in dots_item.findChildren(QObject)
                         if c.metaObject().className().startswith("QQuickRepeater")), None)
    if dot_repeater is None or dot_repeater.property("count") != 3:
        print(f"FAIL: expected 3 interlude dots, got "
              f"{dot_repeater.property('count') if dot_repeater else None}")
        return 1
    dot_opacities = []
    for i in range(3):
        expr = QQmlExpression(engine.rootContext(), dot_repeater, f"itemAt({i})")
        item, errored = expr.evaluate()
        if errored or item is None:
            print(f"FAIL: interlude dot itemAt({i}) errored: {expr.error()}")
            return 1
        dot_opacities.append(float(item.property("opacity") or 0))
    lit = [o for o in dot_opacities if o > 0.05]
    if not lit:
        print(f"FAIL: interlude dots should be lit mid-gap, "
              f"opacities={[round(o, 3) for o in dot_opacities]}")
        return 1
    print(f"interlude: {len(lit)}/3 dots breathing, lyrics row hidden", flush=True)

    # 间奏结束 → 主行回来，点退场
    backend.set_interlude(False)
    _wait(150)
    if root.property("interludeActive"):
        print("FAIL: interlude should clear when gap ends")
        return 1
    if not _find_sweep().property("visible"):
        print("FAIL: lyrics row should come back after interlude")
        return 1
    print("interlude: lyrics row restored after gap", flush=True)

    # 无可用歌词时收起：不可见 + actualVisible 归 false，但组件本身仍留在宿主列表里
    # （height / implicitWidth 原样保留，不再像旧实现那样把高度也绑成 0）。
    # loading 保持占位避免闪烁；ready 再恢复显示，无需重新登记。
    backend.set_state("nomatch")
    _wait(450)  # 等退场动画（最长 250ms）播完
    if (root.property("shouldShow") or root.property("visible")
            or root.property("actualVisible")):
        print(f"FAIL: nomatch should hide widget, "
              f"shouldShow={root.property('shouldShow')} "
              f"visible={root.property('visible')} "
              f"actualVisible={root.property('actualVisible')}")
        return 1
    hidden_h = float(root.property("height") or 0)
    if hidden_h < 1:
        print(f"FAIL: hidden widget must keep its height so it stays in the host "
              f"component list, got h={hidden_h}")
        return 1
    backend.set_state("loading")
    _wait(150)
    if not root.property("shouldShow"):
        print("FAIL: loading must keep widget visible to avoid flicker")
        return 1
    backend.set_state("ready")
    _wait(500)  # 等入场动画把组件重新显示出来
    if (not root.property("shouldShow") or not root.property("visible")
            or not root.property("actualVisible")):
        print(f"FAIL: ready should restore widget, "
              f"shouldShow={root.property('shouldShow')} "
              f"visible={root.property('visible')} "
              f"actualVisible={root.property('actualVisible')}")
        return 1
    print("visibility: nomatch hides (stays in list), loading holds, ready restores",
          flush=True)

    # 字体设置：原文/译文分别生效；译文回退到下一句时仍用原文字体
    configs.set_pref("lyric_font_original", "Consolas")
    configs.set_pref("lyric_font_weight_original", 700)
    configs.set_pref("lyric_font_translation", "Courier New")
    configs.set_pref("lyric_font_weight_translation", 300)
    _wait(50)
    if root.property("originalFontFamily") != "Consolas":
        print(f"FAIL: original font family, got {root.property('originalFontFamily')}")
        return 1
    if int(root.property("originalFontWeight") or 0) != 700:
        print(f"FAIL: original font weight, got {root.property('originalFontWeight')}")
        return 1
    if root.property("translationFontFamily") != "Courier New":
        print(f"FAIL: translation font family, got {root.property('translationFontFamily')}")
        return 1
    print("fonts: original/translation settings apply live", flush=True)

    # ---- 日语独立字体 + 振假名 ----
    # 日语字体只对「含假名」的行生效：非日语行应回落到原文字体。
    configs.set_pref("lyric_font_japanese", "Yu Gothic")
    configs.set_pref("lyric_font_weight_japanese", 500)
    backend.set_line(
        [{"text": "涙", "startMs": 0, "endMs": 1000, "ruby": "なみだ"},
         {"text": "の", "startMs": 1000, "endMs": 1500, "ruby": ""},
         {"text": "雨", "startMs": 1500, "endMs": 2600, "ruby": "あめ"}],
        True, "", japanese=True)
    backend.set_position(200)
    _wait(120)
    if root.property("japaneseFontFamily") != "Yu Gothic":
        print(f"FAIL: japanese font family, got {root.property('japaneseFontFamily')}")
        return 1
    if int(root.property("japaneseFontWeight") or 0) != 500:
        print(f"FAIL: japanese font weight, got {root.property('japaneseFontWeight')}")
        return 1
    sweep = _find_sweep()
    if sweep is None:
        print("FAIL: sweep not found for furigana assertions")
        return 1
    eff, _ = QQmlExpression(engine.rootContext(), sweep, "effectiveFontFamily").evaluate()
    if eff != "Yu Gothic":
        print(f"FAIL: japanese line should use japanese font, got {eff}")
        return 1

    # 非日语行：即使配了日语字体也必须回落到原文字体，避免误伤中文/英文歌词
    backend.set_line([{"text": "晴天", "startMs": 0, "endMs": 1000, "ruby": ""}],
                     True, "", japanese=False)
    _wait(120)
    eff, _ = QQmlExpression(engine.rootContext(), sweep, "effectiveFontFamily").evaluate()
    if eff != "Consolas":
        print(f"FAIL: non-japanese line must fall back to original font, got {eff}")
        return 1

    # 振假名渲染：汉字上方小字，字号约主字号 0.42 倍，行高随之抬升
    backend.set_line(
        [{"text": "涙", "startMs": 0, "endMs": 1000, "ruby": "なみだ"}],
        True, "", japanese=True)
    _wait(150)
    row = _find_wordrow()
    if row is None:
        print("FAIL: wordRow not found for furigana assertion")
        return 1
    rep_list = [o for o in row.findChildren(QObject)
                if o.metaObject().className().startswith("QQuickRepeater")]
    if not rep_list:
        print("FAIL: Repeater not found for furigana assertion")
        return 1
    rep = rep_list[0]
    word_item, _ = QQmlExpression(engine.rootContext(), rep, "itemAt(0)").evaluate()
    if word_item is None:
        print("FAIL: Repeater.itemAt(0) returned None")
        return 1
    ruby_items = [o for o in word_item.findChildren(QObject)
                  if o.objectName() == "rubyText"]
    if len(ruby_items) != 1:
        print(f"FAIL: expect 1 rubyText for 1 word, got {len(ruby_items)}")
        return 1
    ruby = ruby_items[0]
    ruby_str, _ = QQmlExpression(engine.rootContext(), ruby, "text").evaluate()
    if ruby_str != "なみだ":
        print(f"FAIL: ruby text should be なみだ, got {ruby_str!r}")
        return 1
    ruby_px, _ = QQmlExpression(engine.rootContext(), ruby, "font.pixelSize").evaluate()
    ruby_vis, _ = QQmlExpression(engine.rootContext(), ruby, "visible").evaluate()
    if not ruby_vis:
        print("FAIL: ruby should be visible for a word carrying kana reading")
        return 1
    if not (8 <= int(ruby_px) <= 18) or int(ruby_px) >= int(root.property("titlePx")):
        print(f"FAIL: ruby pixel size should be a small fraction of the main size, "
              f"got {ruby_px} vs main {root.property('titlePx')}")
        return 1

    # 关掉总开关：假名必须立刻消失（数据仍在，只是不渲染）
    configs.set_pref("lyric_furigana_enabled", False)
    _wait(150)
    ruby_vis, _ = QQmlExpression(engine.rootContext(), ruby, "visible").evaluate()
    if ruby_vis:
        print("FAIL: disabling lyric_furigana_enabled must hide ruby")
        return 1
    configs.set_pref("lyric_furigana_enabled", True)
    _wait(150)
    ruby_vis, _ = QQmlExpression(engine.rootContext(), ruby, "visible").evaluate()
    if not ruby_vis:
        print("FAIL: re-enabling lyric_furigana_enabled must show ruby again")
        return 1
    print("furigana: kana rendered above kanji, gated by setting, japanese font scoped",
          flush=True)

    # ---- 整行统一预留：同行每个 delegate 的 rubyHeight 必须相同 ----
    # 曾经的实现是「按词各自预留」（rubyHeight = 该词 rubyText 的隐式高度），
    # 于是同一行里有注音的词被推低 12px、没注音的词留在原位，主字高低错落；
    # 且整行高度随注音出现而变，verticalCenter 会把整行连同副行一起挪位。
    # 现在改成行级统一预留（sweep.lineReservedRuby），下面钉死这条不变量。
    backend.set_line(
        [{"text": "涙", "startMs": 0, "endMs": 500, "ruby": "なみだ"},
         {"text": "の", "startMs": 500, "endMs": 800, "ruby": ""},
         {"text": "雨", "startMs": 800, "endMs": 1400, "ruby": "あめ"}],
        True, "", japanese=True)
    _wait(150)
    row = _find_wordrow()
    rep_list = [o for o in row.findChildren(QObject)
                if o.metaObject().className().startswith("QQuickRepeater")]
    rep = rep_list[0]
    heights = []
    for i in range(3):
        d, _ = QQmlExpression(engine.rootContext(), rep, f"itemAt({i})").evaluate()
        if d is None:
            print(f"FAIL: itemAt({i}) None in uniform-ruby assertion")
            return 1
        h, _ = QQmlExpression(engine.rootContext(), d, "rubyHeight").evaluate()
        heights.append(h)
    if len(set(round(float(h), 3) for h in heights)) != 1:
        print(f"FAIL: 同一行 rubyHeight 必须整行统一，got {heights}"
              f"（逐词预留会让无注音的词留在原位、有注音的词被推低）")
        return 1
    if abs(float(heights[0])) < 0.01:
        print("FAIL: 该行有注音数据，rubyHeight 不应为 0")
        return 1
    # 关掉总开关后整行预留必须归零
    configs.set_pref("lyric_furigana_enabled", False)
    _wait(150)
    d1, _ = QQmlExpression(engine.rootContext(), rep, "itemAt(1)").evaluate()
    h_off, _ = QQmlExpression(engine.rootContext(), d1, "rubyHeight").evaluate()
    if h_off is None or abs(float(h_off)) > 0.01:
        print(f"FAIL: 关闭振假名后整行预留应归零，got {h_off}")
        return 1
    configs.set_pref("lyric_furigana_enabled", True)
    _wait(150)
    print("furigana: 整行统一预留（同行所有词共底，开关关闭时归零）", flush=True)

    configs.set_pref("lyric_font_japanese", "")
    configs.set_pref("lyric_font_weight_japanese", 0)
    backend.set_line(
        [{"text": "晴天", "startMs": 1000, "endMs": 1600, "ruby": ""},
         {"text": " ", "startMs": 1600, "endMs": 2600, "ruby": ""},
         {"text": "周杰伦", "startMs": 2600, "endMs": 3800, "ruby": ""}],
        True, "Sunny day", japanese=False)
    _wait(100)

    # ---- 换行 / 换歌动画（大幅度动效） ----
    # 旧实现换行只有 opacity 0.35→1（260ms），用户反馈「看不出换行」。
    # 新实现由 root.lineSweepPulse（0→1 归一化进度）驱动三层可见效果：
    #   a) 每个词从下方行高的 34% 处、1.32 倍缩放入场，走过冲回弹
    #   b) sweepRow 整体做一次 1.05 倍呼吸缩放（整行统一，不逐词算）
    #   c) 一条横向扫掠高光从左扫到右
    # 断言必须打在**真实判据**上：只有断言 delegate 的 y / scale，以及
    # sweepRow.scale、高光 rect 的 visible，才能在实现被换回旧版时 FAIL。
    # 断言 root.lineSweepPulse 本身是不够的（旧版没这个属性，会是 None 而假绿/假红）。
    backend.set_state("ready")
    backend.set_line(
        [{"text": "晴", "startMs": 1000, "endMs": 1600, "ruby": ""},
         {"text": "天", "startMs": 1600, "endMs": 2600, "ruby": ""},
         {"text": "好", "startMs": 2600, "endMs": 3800, "ruby": ""}],
        True, "", japanese=False)
    _wait(400)
    sweep = _find_sweep()
    row = _find_wordrow()
    rep = next(o for o in row.findChildren(QObject)
               if o.metaObject().className().startswith("QQuickRepeater"))

    def _delegate_y(i):
        # 位移走 transform（Row 会重设子项 y，直接写 y 属性会被无声吃掉）
        d, _ = QQmlExpression(engine.rootContext(), rep, f"itemAt({i})").evaluate()
        ty, _ = QQmlExpression(engine.rootContext(), d, "transform[0].y").evaluate()
        return float(ty) if ty is not None else 0.0

    def _delegate_scale(i):
        d, _ = QQmlExpression(engine.rootContext(), rep, f"itemAt({i})").evaluate()
        return float(d.property("scale") or 1)

    # 静息态：动画播完后所有词必须精确归位，斜着的字不能留在屏幕上
    for i in range(3):
        if abs(_delegate_y(i)) > 0.01 or abs(_delegate_scale(i) - 1.0) > 0.001:
            print(f"FAIL: 换行动画播完后 word{i} 必须回到 y=0 / scale=1，"
                  f"got y={_delegate_y(i)} scale={_delegate_scale(i)}")
            return 1
    if abs(float(sweep.property("scale")) - 1.0) > 0.001:
        print(f"FAIL: 换行动画播完后 sweepRow.scale 必须为 1，"
              f"got {sweep.property('scale')}")
        return 1
    print("animation: 换行动画播完后逐词与整行精确归位（y=0 / scale=1）", flush=True)

    # 换行瞬间：重新触发一条新行，立刻采样入场中间态。
    # 这里不能用 app.processEvents()——它不推进 QAbstractAnimation 的时钟，
    # 动画进度会停在 0，位移自然也是 0（假 FAIL）。用 _wait 让事件循环真正跑起来。
    backend.set_line(
        [{"text": "雨", "startMs": 0, "endMs": 600, "ruby": ""},
         {"text": "还", "startMs": 600, "endMs": 1200, "ruby": ""},
         {"text": "下", "startMs": 1200, "endMs": 1800, "ruby": ""}],
        True, "", japanese=False)
    _wait(90)

    pulse_mid, _ = QQmlExpression(engine.rootContext(), root, "lineSweepPulse").evaluate()
    if pulse_mid is None or float(pulse_mid) <= 0.0 or float(pulse_mid) >= 0.999:
        print(f"FAIL: 换行瞬间 lineSweepPulse 应处于 0→1 之间，got {pulse_mid}"
              f"（换行没有重启动画进度）")
        return 1

    # 错峰：靠后的词 delay 更大 → 同一时刻入场进度更小 → 位移更大。
    # 这条把「逐词错峰」与「整行一起动」区分开，是灵动感的关键。
    y0, y1, y2 = _delegate_y(0), _delegate_y(1), _delegate_y(2)
    if not (y0 <= y2 + 0.01 and y1 <= y2 + 0.01 and y2 > 0.05):
        print(f"FAIL: 逐词应错峰入场且尚未归位，got y=[{y0:.2f}, {y1:.2f}, {y2:.2f}]"
              f"（没有逐词错峰 = 整行一起淡入，缺灵动感）")
        return 1
    s2 = _delegate_scale(2)
    if not (s2 > 1.02 and s2 < 1.5):
        print(f"FAIL: 入场中的词应为放大态（约 1.32 起步），got scale={s2:.3f}")
        return 1
    sweep_scale, _ = QQmlExpression(engine.rootContext(), sweep, "scale").evaluate()
    if sweep_scale is None or abs(float(sweep_scale) - 1.0) < 1e-6:
        print(f"FAIL: 换行期间 sweepRow 应有整体呼吸缩放，got scale={sweep_scale}")
        return 1
    highlight = next((o for o in root.findChildren(QObject)
                      if o.property("objectName") == "lineSweepHighlight"), None)
    if highlight is None:
        print("FAIL: 找不到换行扫掠高光 lineSweepHighlight")
        return 1
    if not highlight.property("visible"):
        print("FAIL: 换行期间扫掠高光应可见")
        return 1
    print(f"animation: 逐词错峰入场 y=[{y0:.1f},{y1:.1f},{y2:.1f}] "
          f"scale={s2:.2f}，整行呼吸 {float(sweep_scale):.3f}，扫掠高光可见", flush=True)

    # 动画必须自然收尾，不能永久停在中间态
    _wait(900)
    for i in range(3):
        if abs(_delegate_y(i)) > 0.01 or abs(_delegate_scale(i) - 1.0) > 0.001:
            print(f"FAIL: 换行动画应自动收尾，word{i} 停在 y={_delegate_y(i)} "
                  f"scale={_delegate_scale(i)}")
            return 1
    if highlight.property("visible"):
        print("FAIL: 动画结束后扫掠高光必须隐藏")
        return 1
    if float(sweep.property("scale") or 1) != 1.0:
        print("FAIL: 动画结束后整行缩放必须回到 1")
        return 1
    print("animation: 换行动画自动收尾（词归位、高光隐藏、整行缩放复位）", flush=True)

    # 关掉「换行与换歌动画」→ 各层直接落到终态，等价旧版轻量淡入
    configs.set_pref("lyric_animation_enabled", False)
    _wait(120)
    backend.set_line(
        [{"text": "收", "startMs": 0, "endMs": 600, "ruby": ""},
         {"text": "尾", "startMs": 600, "endMs": 1200, "ruby": ""},
         {"text": "。", "startMs": 1200, "endMs": 1800, "ruby": ""}],
        True, "", japanese=False)
    _wait(90)
    off_y = _delegate_y(2)
    off_s = _delegate_scale(2)
    if abs(off_y) > 0.01 or abs(off_s - 1.0) > 0.001:
        print(f"FAIL: 关闭换行与换歌动画后不应有入场位移/缩放，got y={off_y} scale={off_s}")
        return 1
    if highlight.property("visible"):
        print("FAIL: 关闭换行与换歌动画后扫掠高光必须不出现")
        return 1
    print("animation: 关闭换行与换歌动画后回落到无位移的轻量淡入", flush=True)
    configs.set_pref("lyric_animation_enabled", True)
    _wait(120)

    # ---- 换歌整组件横扫 ----
    # 后端 _on_song_changed 的第一件事是把 state 从 "ready" 归到 "idle"，随后立刻转
    # loading。这条 ready → idle 的下降沿就是换歌信号（首次加载 / 重试 / 改歌词源都
    # 不会从 ready 掉回 idle）。用户换歌时整块内容向右抖出、再从左侧大幅滑入。
    backend.set_state("idle")
    _wait(60)
    backend.set_state("ready")
    _wait(1200)
    prev_ready, _ = QQmlExpression(engine.rootContext(), root, "previousState").evaluate()
    if prev_ready != "ready":
        print(f"FAIL: 换歌前置条件不满足，previousState 应为 ready，got {prev_ready}")
        return 1
    content_row = next((o for o in root.findChildren(QObject)
                        if o.property("objectName") == "contentRow"), None)
    if content_row is None:
        # 桩布局里找不到时的兜底：换歌动画挂在 sweepRow 的父容器上
        content_row = sweep.parent()
    if content_row is None:
        print("FAIL: 找不到换歌动画的目标容器")
        return 1

    # 位移走 transform：contentRow 有 anchors.left，锚点会覆盖 x 属性，
    # 用 x 做位移动画会被静默吃掉（实测 songSlideX 在动、x 恒为 0）。
    def _row_tx():
        v, _ = QQmlExpression(engine.rootContext(), content_row, "transform[0].x").evaluate()
        return float(v) if v is not None else 0.0

    # idle → ready 只是就绪，不应播横扫（否则首次加载也会晃）
    if abs(_row_tx()) > 0.01:
        print(f"FAIL: ready（就绪）不应触发换歌横扫，got {_row_tx()}")
        return 1

    # 换歌：ready → idle（真后端 _on_song_changed 的第一步）
    backend.set_state("idle")
    _wait(70)
    song_x = _row_tx()
    song_op, _ = QQmlExpression(engine.rootContext(), content_row, "opacity").evaluate()
    if abs(song_x) < 1.0:
        sw, _ = QQmlExpression(engine.rootContext(), root, "songSweeping").evaluate()
        print(f"FAIL: 换歌瞬间 contentRow 应有横向位移，got x={song_x}"
              f"（换歌动画没有触发；songSweeping={sw} "
              f"state={backend.property('state')}）")
        return 1
    if float(song_op) >= 1.0:
        print(f"FAIL: 换歌瞬间 contentRow 应淡出，got opacity={song_op}")
        return 1
    print(f"animation: 换歌整块横扫 x={song_x:.1f} "
          f"opacity={float(song_op):.2f}", flush=True)

    backend.set_state("ready")
    _wait(1200)
    rest_x = _row_tx()
    rest_op, _ = QQmlExpression(engine.rootContext(), content_row, "opacity").evaluate()
    if abs(rest_x) > 0.01:
        print(f"FAIL: 换歌动画结束后 contentRow 位移必须回 0，got {rest_x}")
        return 1
    if rest_op is None or abs(float(rest_op) - 1.0) > 0.001:
        print(f"FAIL: 换歌动画结束后 contentRow.opacity 必须回 1，got {rest_op}")
        return 1
    sweeping_after, _ = QQmlExpression(engine.rootContext(), root, "songSweeping").evaluate()
    if sweeping_after:
        print("FAIL: 换歌动画结束后 songSweeping 必须复位，否则第二次换歌不再播放")
        return 1
    print("animation: 换歌横扫收尾后精确归位（位移=0 / opacity=1 / 标志复位）", flush=True)

    # 改歌词源 / 重新抓取（ready → loading，不经过 idle）不应误播换歌动画
    backend.set_state("loading")
    _wait(70)
    src_x = _row_tx()
    if abs(src_x) > 0.01:
        print(f"FAIL: ready→loading（改歌词源/重抓）不应触发换歌动画，got x={src_x}")
        return 1
    print("animation: 仅换歌触发整块横扫（改歌词源不误播）", flush=True)
    backend.set_state("ready")
    _wait(150)

    # ---- 真后端 × 真组件：间奏信号的时序契约 ----
    # 上面的间奏断言都走桩后端（set_interlude 先置位再 emit），因此掩盖了真后端
    # _show_interlude() 里「先 emit 再置位」的顺序错误：QML 绑定在 emit 的同一时刻
    # 求值，只会读到旧的 False，而此后整个间奏期间不再有第二次 emit →
    # root.interludeActive 恒为 false，三点呼吸点在真机上永不显示。
    # 真后端 + 真组件走一遍才能钉住这条契约，别退化回桩后端。
    sys.path.insert(0, str(PLUGIN_DIR))
    import lyrics_providers as lp
    from lyrics_backend import LyricsBackend

    class InterludeMedia(StubMedia):
        songChanged = Signal(str, str)

        def __init__(self):
            super().__init__()
            self.duration_ms = 200000
            self._pos = 0

        def current_position_ms(self):
            return self._pos

    def _gap_line(start, end, text):
        return lp.LyricLine(start, end, text, [lp.LyricWord(start, end, text)], None)

    gap_doc = lp.LyricsDocument([
        _gap_line(1000, 3000, "第一句"),
        _gap_line(4000, 6000, "第二句"),
        _gap_line(14000, 16000, "第三句"),
    ], "qqmusic", "间奏测试")

    gap_media = InterludeMedia()
    real_backend = LyricsBackend(
        gap_media, lambda key: None,
        cache_dir=Path(tempfile.mkdtemp(dir=STUB_TMP_DIR)),
        fetch_func=lambda *a: (gap_doc, "qqmusic"))
    real_backend._on_song_changed("间奏测试", "艺")
    real_backend._fetch_worker(real_backend._gen, "间奏测试", "艺",
                               gap_media.duration_ms, "auto")
    root.setProperty("backend", real_backend)
    _wait(80)

    gap_media._pos = 5000        # 第二句唱中：不是间奏
    real_backend._on_tick()
    _wait(80)
    if root.property("interludeActive"):
        print("FAIL: real backend must not report interlude while a line is sung")
        return 1

    gap_media._pos = 6000        # 落进 [6000, 13750) 间奏区间
    real_backend._on_tick()
    _wait(80)
    if not root.property("interludeActive"):
        print("FAIL: interlude never reached the QML binding through the real backend "
              "(interludeChanged emitted before the state was flipped?)")
        return 1
    real_dots = next((o for o in root.findChildren(QObject)
                      if o.property("objectName") == "interludeDots"), None)
    if real_dots is None or not real_dots.property("visible"):
        print("FAIL: interlude dots stay hidden with the real backend in interlude")
        return 1
    real_sweep = _find_sweep()
    if real_sweep is not None and real_sweep.property("visible"):
        print("FAIL: lyrics row must give way to dots during a real-backend interlude")
        return 1

    # 间奏中段：呼吸点必须真的点亮（位置/区间都由真后端提供，而非桩常量）
    gap_media._pos = 9000
    real_backend._on_tick()
    _wait(150)
    real_dot_repeater = next((c for c in real_dots.findChildren(QObject)
                              if c.metaObject().className().startswith("QQuickRepeater")), None)
    if real_dot_repeater is None or real_dot_repeater.property("count") != 3:
        print("FAIL: real-backend interlude should own exactly 3 dots")
        return 1
    real_opacities = []
    for i in range(3):
        expr = QQmlExpression(engine.rootContext(), real_dot_repeater, f"itemAt({i})")
        item, errored = expr.evaluate()
        if errored or item is None:
            print(f"FAIL: real-backend dot itemAt({i}) errored: {expr.error()}")
            return 1
        real_opacities.append(float(item.property("opacity") or 0))
    if not [o for o in real_opacities if o > 0.05]:
        print(f"FAIL: real-backend dots never light up, "
              f"opacities={[round(o, 3) for o in real_opacities]}")
        return 1
    print(f"interlude: real backend drives {len([o for o in real_opacities if o > 0.05])}/3 "
          f"breathing dots through QML bindings", flush=True)

    gap_media._pos = 13800       # 提前量窗口：交回下一句预览，间奏关闭
    real_backend._on_tick()
    _wait(80)
    if root.property("interludeActive"):
        print("FAIL: interlude should clear when the real gap ends")
        return 1
    print("interlude: real backend releases dots back to the next line", flush=True)

    print("PASS: lyrics widget loaded and renders word delegates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
