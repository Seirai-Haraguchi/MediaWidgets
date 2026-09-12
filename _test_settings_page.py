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
    sourceNameChanged = Signal()
    sourceIconChanged = Signal()

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

    @Property(str, notify=sourceNameChanged)
    def sourceName(self):
        return "NetEase Cloud Music"

    @Property(str, notify=sourceIconChanged)
    def sourceIcon(self):
        return ""


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
                        "show_source_badge": False,
                        "media_gradient_background": True,
                        "media_gradient_intensity": 100,
                        "media_background_progress": True,
                        "media_background_progress_text": True,
                        "media_subtitle_content": "artist",
                        "lyric_gradient_background": True,
                        "lyric_gradient_intensity": 100,
                        "lyric_subtitle_content": "translation_or_next",
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

    # 给个确定宽度让布局完成隐式尺寸计算，再验证插件自带 Pivot：
    # PivotItem 子项由 Pivot 自动注册成等量页签头（声明式，非 model/Repeater），
    # 默认选中首项；页面常驻，仅切换可见性，Pivot 高度随当前页内容自适应。
    root.setProperty("width", 900)
    app.processEvents()

    def find_object(name):
        return next((item for item in root.findChildren(QObject)
                    if item.property("objectName") == name), None)

    pivot = find_object("widgetPivot")
    tab_bar = find_object("widgetPivotBar")
    media_page = find_object("mediaSettingsPage")
    lyric_page = find_object("lyricSettingsPage")
    if pivot is None or tab_bar is None or media_page is None or lyric_page is None:
        print("FAIL: widget customization Pivot pages missing", flush=True)
        return 1

    # 页签数量与 PivotItem 一一对应：注册了几个页、页签头就建几个
    # （TabBar.itemAt 返回的 QQuickItem* 无法被 PySide 包装，故按子对象枚举）
    headers = [
        item for item in tab_bar.findChildren(QObject)
        if item.metaObject().indexOfProperty("checked") >= 0
    ]
    if pivot.property("count") != 2 or tab_bar.property("count") != 2 or len(headers) != 2:
        print("FAIL: widget customization Pivot did not register 2 tabs", flush=True)
        return 1

    # 页索引必须与声明顺序一致：姊妹项的 Component.onCompleted 触发次序与
    # 声明次序相反，这里是「页签顺序不被反转」的回归守卫
    pages = [(media_page, "媒体组件", 0), (lyric_page, "歌词组件", 1)]
    if [page.property("__index") for page, _, _ in pages] != [0, 1]:
        print("FAIL: Pivot pages registered out of declaration order", flush=True)
        return 1
    for page, label, _ in pages:
        header = next((h for h in headers if h.property("text") == label), None)
        if header is None:
            print(f"FAIL: no Pivot header built for '{label}'", flush=True)
            return 1
        # 页签头图标经 header.icon.name -> IconWidget.icon 落地，
        # QQuickIcon 组属性无法跨语言读取，故校验内部 IconWidget 的 icon 串
        icon_widget = next(
            (c for c in header.findChildren(QObject)
             if c.metaObject().indexOfProperty("isFontIcon") >= 0),
            None,
        )
        if icon_widget is None or icon_widget.property("icon") != page.property("iconName"):
            print(f"FAIL: Pivot header icon for '{label}' not wired to PivotItem", flush=True)
            return 1
    print("widget customization: Pivot registered 2 tabs from PivotItem children", flush=True)

    # 默认选中首个页签：仅媒体页可见，且当前页有自适应高度
    if pivot.property("currentIndex") != 0:
        print("FAIL: widget customization Pivot default tab not selected", flush=True)
        return 1
    if not media_page.property("visible") or lyric_page.property("visible"):
        print("FAIL: widget customization Pivot default page not shown", flush=True)
        return 1
    if media_page.property("implicitHeight") <= 0:
        print("FAIL: media settings page has no height", flush=True)
        return 1

    # 切到歌词组件页签：页面常驻不销毁，仅切换可见性，Pivot 高度随内容重算
    pivot.setProperty("currentIndex", 1)
    app.processEvents()
    if pivot.property("currentIndex") != 1:
        print("FAIL: widget customization Pivot cannot switch tabs", flush=True)
        return 1
    if not lyric_page.property("visible") or media_page.property("visible"):
        print("FAIL: widget customization Pivot tab switch not applied", flush=True)
        return 1
    if lyric_page.property("implicitHeight") <= 0:
        print("FAIL: lyric settings page has no height", flush=True)
        return 1
    # 索引与页签头必须对应：选中第 2 项时应当是高亮的「歌词组件」页签头
    checked = next((h.property("text") for h in headers if h.property("checked")), None)
    if checked != "歌词组件":
        print("FAIL: Pivot tab index does not map to expected header", flush=True)
        return 1
    if media_page.property("__pivot") is not pivot:
        print("FAIL: Pivot page lost its host on tab switch", flush=True)
        return 1
    print("widget customization: lyric tab shown with adaptive height", flush=True)

    # 图标名必须存在于 RinUI 字体图标索引（缺失即页面“缺图标”）
    icon_names = [
        "ic_fluent_music_note_2_20_regular",
        "ic_fluent_pause_20_regular",
        "ic_fluent_play_20_regular",
        "ic_fluent_album_20_regular",
        "ic_fluent_slide_text_20_regular",
        "ic_fluent_app_generic_20_regular",
        "ic_fluent_paint_brush_20_regular",
        "ic_fluent_transparency_square_20_regular",
        "ic_fluent_data_bar_horizontal_20_regular",
        "ic_fluent_timer_20_regular",
        "ic_fluent_text_description_20_regular",
        "ic_fluent_cloud_arrow_down_20_regular",
        "ic_fluent_translate_20_regular",
        "ic_fluent_text_font_20_regular",
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
