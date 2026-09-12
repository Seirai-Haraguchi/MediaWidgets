"""开发用冒烟测试：独立 QML 引擎加载媒体组件，验证语法 / 播放源图标角标逻辑。

不依赖 CW2 运行时：Widget 与 ClassWidgets.Theme 用最小桩模块模拟；
RinUI / AppCentral / Utils / Configs / backend 用 Python 桩注入
（复用 _test_lyrics_widget.py 的桩方案，backend 属性可变以便驱动角标状态）。
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)

PLUGIN_DIR = Path(__file__).parent
STUB_TMP_DIR = PLUGIN_DIR / ".tmp"
PLUGIN_ID = "com.seiraiharaguchi.mediawidgets"


def build_stub_module():
    """最小 ClassWidgets.Theme 桩：Widget / Title，接口与 CW2 真实组件一致。"""
    STUB_TMP_DIR.mkdir(parents=True, exist_ok=True)
    mod_dir = Path(tempfile.mkdtemp(prefix="cw_theme_stub_", dir=STUB_TMP_DIR)) / "ClassWidgets" / "Theme"
    mod_dir.mkdir(parents=True)
    (mod_dir / "qmldir").write_text(
        "module ClassWidgets.Theme\n"
        "Widget 2.0 Widget.qml\n"
        "Title 2.0 Title.qml\n",
        encoding="utf-8")
    (mod_dir / "Widget.qml").write_text(
        "import QtQuick\n"
        "Item {\n"
        "    id: widgetBase\n"
        "    property string text: ''\n"
        "    property bool miniMode: false\n"
        "    property var backend: null\n"
        "    property real cornerRadius: height * 0.22\n"
        "    property real padding: miniMode ? 16 : 24\n"
        "    property alias backgroundArea: backgroundArea.children\n"
        "    default property alias content: contentArea.data\n"
        "    implicitWidth: 260\n"
        "    height: miniMode ? 56 : 100\n"
        "    Rectangle {\n"
        "        anchors.fill: parent\n"
        "        radius: height * 0.22\n"
        "        color: Qt.rgba(0.98, 0.98, 1.0, 0.7)\n"
        "    }\n"
        "    Item { id: backgroundArea; anchors.fill: parent }\n"
        "    Item { id: contentArea; anchors.fill: parent }\n"
        "}\n",
        encoding="utf-8")
    (mod_dir / "Title.qml").write_text(
        "import QtQuick\n"
        "Text {}\n",
        encoding="utf-8")
    return mod_dir.parent.parent


def build_stub_rinui():
    """最小 RinUI 桩（Theme/Utils 单例），避免真实单例的初始化依赖。"""
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


def build_stub_effects():
    """最小 Qt5Compat.GraphicalEffects 桩：只声明 OpacityMask 形状（不开窗口渲染）。"""
    mod_dir = (Path(tempfile.mkdtemp(prefix="effects_stub_", dir=STUB_TMP_DIR))
               / "Qt5Compat" / "GraphicalEffects")
    mod_dir.mkdir(parents=True)
    (mod_dir / "qmldir").write_text(
        "module Qt5Compat.GraphicalEffects\n"
        "OpacityMask 2.0 OpacityMask.qml\n",
        encoding="utf-8")
    (mod_dir / "OpacityMask.qml").write_text(
        "import QtQuick\n"
        "Item {\n"
        "    property var source: null\n"
        "    property var maskSource: null\n"
        "}\n",
        encoding="utf-8")
    return mod_dir.parent.parent


class StubMedia(QObject):
    """媒体后端桩：属性可变，用于驱动角标及背景偏好。"""
    titleChanged = Signal()
    artistChanged = Signal()
    artChanged = Signal()
    progressChanged = Signal()
    playingChanged = Signal()
    accentColorChanged = Signal()
    accentColor2Changed = Signal()
    sourceIconChanged = Signal()

    def __init__(self):
        super().__init__()
        self._title = ""
        self._art = ""
        self._source_icon = ""

    @Property(str, notify=titleChanged)
    def title(self):
        return self._title

    @title.setter
    def title(self, v):
        self._title = v
        self.titleChanged.emit()

    @Property(str, constant=True)
    def artist(self):
        return "周杰伦"

    @Property(str, notify=artChanged)
    def art(self):
        return self._art

    @art.setter
    def art(self, v):
        self._art = v
        self.artChanged.emit()

    @Property(float, constant=True)
    def progress(self):
        return 0.42

    @Property(str, constant=True)
    def positionText(self):
        return "1:23"

    @Property(str, constant=True)
    def durationText(self):
        return "4:29"

    @Property(str, constant=True)
    def accentColor(self):
        return "#7C4DFF"

    @Property(str, constant=True)
    def accentColor2(self):
        return "#4DB6AC"

    @Property(bool, constant=True)
    def isPlaying(self):
        return True

    @Property(str, notify=sourceIconChanged)
    def sourceIcon(self):
        return self._source_icon

    @sourceIcon.setter
    def sourceIcon(self, v):
        self._source_icon = v
        self.sourceIconChanged.emit()


class StubConfigs(QObject):
    configChanged = Signal()

    def __init__(self):
        super().__init__()
        self._prefs = {
            "show_source_badge": False,
            "media_gradient_background": True,
            "media_gradient_intensity": 100,
            "media_background_progress": True,
            "media_background_progress_text": True,
            "media_subtitle_content": "artist",
        }

    def set_pref(self, key, value):
        self._prefs[key] = value
        self.configChanged.emit()

    @Property("QVariant", notify=configChanged)
    def data(self):
        return {
            "preferences": {"font": "", "font_weight": 600, "mini_mode": False},
            "plugins": {"configs": {PLUGIN_ID: dict(self._prefs)}},
        }


class StubAppCentral(QObject):
    @Slot(str, str, result=QFont)
    def getQFont(self, family, fallback):
        return QFont(family or fallback or "Arial")


def find_item(root, object_name):
    # 复合组件根对象的 Python 包装是纯 QObject（无 childItems），
    # 循环用 QObject 树查找；角标在 QObject 父子链上，能被扫到
    for child in root.findChildren(QObject):
        try:
            if child.property("objectName") == object_name:
                return child
        except Exception:
            continue
    return None


def main():
    engine = QQmlEngine()
    # 桩模块路径必须在真实 site-packages 之前，保证 import 解析到桩
    engine.addImportPath(str(build_stub_rinui()))
    engine.addImportPath(str(build_stub_module()))
    engine.addImportPath(str(build_stub_effects()))

    media = StubMedia()
    configs = StubConfigs()
    app_central = StubAppCentral()
    engine.rootContext().setContextProperty("AppCentral", app_central)
    engine.rootContext().setContextProperty("Configs", configs)

    problems = []
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType

    def handler(msg_type, context, message):
        if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            problems.append(message)

    qInstallMessageHandler(handler)

    url = QUrl.fromLocalFile(str(PLUGIN_DIR / "qml" / "MediaWidget.qml"))
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
    root.setProperty("backend", media)

    noise_patterns = (
        "theme.qml",
        "Cannot find font directory",
        "ScrollBar attached property must be attached",
    )
    widget_problems = [
        p for p in problems
        if "MediaWidget.qml" in p and not any(pat in p for pat in noise_patterns)
    ]
    for p in widget_problems[:30]:
        print("QML-WARNING:", p)
    if widget_problems:
        print(f"FAIL: {len(widget_problems)} widget warnings")
        return 1
    print("widget: loaded without QML errors", flush=True)

    fails = []

    def check(name, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            fails.append(name)

    badge = find_item(root, "sourceBadge")
    gradient = find_item(root, "gradientBackground")
    background_progress = find_item(root, "backgroundProgress")
    background_progress_text = find_item(root, "backgroundProgressText")
    check("sourceBadge found", badge is not None)
    check("background controls found",
          gradient is not None and background_progress is not None
          and background_progress_text is not None)
    if (badge is None or gradient is None or background_progress is None
            or background_progress_text is None):
        return 1

    # 开关关：无论后端状态如何都不显示
    media.title = "晴天"
    media.sourceIcon = "data:image/png;base64,AAAA"
    check("badge hidden when pref off", not badge.property("visible"))

    # 开关开 + 无图标：不显示
    configs.set_pref("show_source_badge", True)
    media.sourceIcon = ""
    check("badge hidden without icon", not badge.property("visible"))

    # 开关开 + 有图标 + 有媒体：显示
    media.sourceIcon = "data:image/png;base64,AAAA"
    check("badge visible when enabled", badge.property("visible"))

    # 媒体背景各选项：默认开启，修改后应即时驱动对应图层。
    media.art = "data:image/png;base64,AAAA"
    check("gradient shown by default", gradient.property("visible"))
    check("background progress shown by default", background_progress.property("visible"))
    check("background progress text shown by default", background_progress_text.property("visible"))

    configs.set_pref("media_gradient_intensity", 35)
    check("gradient intensity updates live", abs(root.property("gradientIntensity") - 0.35) < 0.001)
    configs.set_pref("media_gradient_background", False)
    check("gradient hides when disabled", not gradient.property("visible"))
    configs.set_pref("media_background_progress", False)
    check("background progress hides when disabled", not background_progress.property("visible"))
    configs.set_pref("media_background_progress_text", False)
    check("background progress text hides when disabled", not background_progress_text.property("visible"))

    configs.set_pref("media_subtitle_content", "progress")
    check("subtitle can show progress", root.property("text") == "1:23 / 4:29",
          root.property("text"))
    configs.set_pref("media_subtitle_content", "artist")
    check("subtitle can show artist", root.property("text") == "周杰伦",
          root.property("text"))

    # Configs 变更通知驱动：重新关掉开关即时隐藏
    configs.set_pref("show_source_badge", False)
    check("badge hides live on pref change", not badge.property("visible"))

    # 无媒体（标题为空）：不显示
    configs.set_pref("show_source_badge", True)
    media.title = ""
    check("badge hidden without media", not badge.property("visible"))

    print()
    print("FAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
