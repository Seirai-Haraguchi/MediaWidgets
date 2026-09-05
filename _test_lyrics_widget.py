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


# ---- ClassWidgets.Theme 桩模块 ----

def build_stub_module():
    """构造可被 import ClassWidgets.Theme 解析的最小模块目录。

    只桩组件类型（Widget/Title/MarqueeTitle），接口与 CW2 真实组件一致；
    Theme/Utils 不在这里桩 —— 它们是 RinUI 单例，组件经 `import RinUI as Rin`
    访问，由 build_stub_rinui 提供同名桩模块。
    """
    mod_dir = Path(tempfile.mkdtemp(prefix="cw_theme_stub_")) / "ClassWidgets" / "Theme"
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
        "    property var backend: null\n"
        "    property real cornerRadius: height * 0.22\n"
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
    mod_dir = Path(tempfile.mkdtemp(prefix="rinui_stub_")) / "RinUI"
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
        return ""

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

    def __init__(self, media, parent=None):
        super().__init__(parent)
        self._media = media
        self._words = [
            {"text": "晴天", "startMs": 1000, "endMs": 1600},
            {"text": " ", "startMs": 1600, "endMs": 2600},
            {"text": "周杰伦", "startMs": 2600, "endMs": 3800},
        ]
        self._position_ms = 1300

    @Property(QObject, constant=True)
    def media(self):
        return self._media

    @Property(str, notify=stateChanged)
    def state(self):
        return "ready"

    @Property(str, notify=lineChanged)
    def lineText(self):
        return "晴天 周杰伦"

    @Property("QVariantList", notify=lineChanged)
    def words(self):
        return self._words

    @Property(str, notify=lineChanged)
    def subLine(self):
        return "Sunny day"

    @Property(bool, notify=lineChanged)
    def subIsTranslation(self):
        return True

    @Property(int, notify=positionChanged)
    def positionMs(self):
        return self._position_ms

    @Property(str, notify=sourceNameChanged)
    def sourceName(self):
        return "QQ音乐"


class StubAppCentral(QObject):
    @Slot(str, str, result=QFont)
    def getQFont(self, family, fallback):
        return QFont(family or fallback or "Arial")


class StubConfigs(QObject):
    configChanged = Signal()

    @Property("QVariant", notify=configChanged)
    def data(self):
        return {
            "preferences": {"font": "", "font_weight": 600, "mini_mode": False},
            "plugins": {"configs": {
                "com.seiraiharaguchi.mediawidgets": {
                    "lyric_source": "auto", "show_translation": True}}},
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

    # 逐字填充结构：每个词 delegate = 底层暗字 + clip 内顶层亮字
    # delegate 自身子项的 QObject 树正常，可用 findChildren
    def _is_text(o):
        cls = o.metaObject().className()
        return cls == "QQuickText" or cls.startswith("Text_")

    texts = [c for c in delegates[0].findChildren(QObject) if _is_text(c)]
    clips = [c for c in delegates[0].findChildren(QObject)
             if c.property("clip") is True]
    if len(texts) != 2 or len(clips) != 1:
        print(f"FAIL: word0 structure: texts={len(texts)} clips={len(clips)}")
        return 1
    clip_item = clips[0]
    top_text = next(t for t in texts if t.parent() is clip_item)
    base_text = next(t for t in texts if t is not top_text)
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
          f"of base {base_text.property('width'):.1f}px", flush=True)

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

    print("PASS: lyrics widget loaded and renders word delegates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
