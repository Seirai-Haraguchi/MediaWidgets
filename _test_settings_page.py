"""开发用冒烟测试：独立 QML 引擎加载设置页，验证语法 / 图标 / 属性引用。

不依赖 CW2 运行时：Configs 与 PluginBackendBridge 用桩对象模拟；
RinUI 以纯 QML 模块方式加载（不走 Python 包装器的窗口初始化）。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtQml import QQmlEngine

from PySide6.QtGui import QGuiApplication

app = QGuiApplication(sys.argv)

RINUI_QML_DIR = (
    Path(__file__).parent / ".venv312" / "Lib" / "site-packages"
)  # 引擎按 <importPath>/RinUI/qmldir 解析模块，需指向包的父目录


class StubBackend(QObject):
    titleChanged = Signal()
    artistChanged = Signal()
    artChanged = Signal()
    progressChanged = Signal()
    playingChanged = Signal()
    accentColorChanged = Signal()

    @Property(str, notify=titleChanged)
    def title(self):
        return "Test Song"

    @Property(str, notify=artistChanged)
    def artist(self):
        return "Test Artist"

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
        return "3:21"

    @Property(str, notify=accentColorChanged)
    def accentColor(self):
        return "#7C4DFF"

    @Property(bool, notify=playingChanged)
    def isPlaying(self):
        return True


class StubConfigs(QObject):
    configChanged = Signal()

    def __init__(self):
        super().__init__()
        self.written = {}
        self._plugins = {
            "plugins": {
                "configs": {
                    "com.seiraiharaguchi.mediawidgets": {
                        "lyrics_enabled": True,
                        "show_translation": False,
                    }
                }
            }
        }

    @Property("QVariant", notify=configChanged)
    def data(self):
        return self._plugins

    # QML 侧 Configs.setPlugin(pid, key, value)
    @Slot(str, str, "QVariant")
    def setPlugin(self, plugin_id, key, value):
        self.written[key] = value
        self.configChanged.emit()


class StubBridge(QObject):
    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    @Slot(str, result=QObject)
    def get_backend(self, plugin_id):
        return self._backend


def main():
    engine = QQmlEngine()
    engine.addImportPath(str(RINUI_QML_DIR))
    print(f"RinUI import path: {RINUI_QML_DIR}", flush=True)

    backend = StubBackend()
    configs = StubConfigs()
    bridge = StubBridge(backend)
    engine.rootContext().setContextProperty("PluginBackendBridge", bridge)
    engine.rootContext().setContextProperty("Configs", configs)

    problems = []
    # 收集 QML 消息（错误与警告）
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType

    def handler(msg_type, context, message):
        if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            problems.append(message)

    qInstallMessageHandler(handler)

    from PySide6.QtQml import QQmlComponent

    url = QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "MediaWidgetsSettings.qml"))
    component = QQmlComponent(engine, url)
    if component.status() == QQmlComponent.Status.Error:
        print("FAIL: component has errors:", flush=True)
        for e in component.errors():
            print(f"  {e}", flush=True)
        return 1

    root = component.create()
    if root is None:
        print("FAIL: create() returned None:", flush=True)
        for e in component.errors():
            print(f"  {e}", flush=True)
        return 1

    print(f"page title: {root.property('title')}", flush=True)
    print(f"backend wired: {root.property('backend') is backend}", flush=True)
    print(f"hasMedia: {root.property('hasMedia')}", flush=True)

    # 图标名必须存在于 RinUI 字体图标索引（缺失即页面“缺图标”）
    icon_names = [
        "ic_fluent_music_note_2_20_regular",
        "ic_fluent_pause_20_regular",
        "ic_fluent_play_20_regular",
        "ic_fluent_alert_on_20_regular",
        "ic_fluent_translate_20_regular",
    ]
    index_js = (
        RINUI_QML_DIR / "RinUI" / "assets" / "fonts" / "FluentSystemIcons-Index.js"
    ).read_text(encoding="utf-8")
    missing = [n for n in icon_names if f'"{n}"' not in index_js]
    if missing:
        print(f"FAIL: icons missing from RinUI index: {missing}", flush=True)
        return 1
    print("icons: all present in FluentSystemIcons index", flush=True)

    # 只统计指向本插件 QML 的警告；RinUI 内部（theme 管理器未随测试初始化）、
    # offscreen 字体目录告警、以及 FluentPage 类型自身的 ScrollBar 复用父级告警
    # （最小纯 FluentPage 页面同样触发，属 RinUI 组件固有行为）都属环境噪音
    noise_patterns = (
        "theme.qml",
        "Cannot find font directory",
        "ScrollBar attached property must be attached",
    )
    page_problems = [
        p for p in problems
        if "MediaWidgetsSettings.qml" in p
        and not any(pat in p for pat in noise_patterns)
    ]
    for p in page_problems[:30]:
        print("QML-WARNING:", p, flush=True)
    if page_problems:
        print(f"FAIL: {len(page_problems)} page warnings", flush=True)
        return 1

    print("PASS: settings page loaded without QML errors", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
