"""开发用冒烟测试：独立 QML 引擎加载设置页，验证语法 / 图标 / 属性引用。

不依赖 CW2 运行时：Configs 与 PluginBackendBridge 用桩对象模拟；
RinUI 以纯 QML 模块方式加载（不走 Python 包装器的窗口初始化）。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot, QCoreApplication
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
                        "lyric_furigana_enabled": True,
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

    # 歌词字体：三类歌词各一张标准 RinUI 设置卡（标题 + 说明 + 字体/字重选择器）。
    # 早期版本用 SettingExpander + SettingItem，宿主里只看得见下拉框、条目标题与说明
    # 被挤没了；这里是「每个选择器都有对应标题与说明」的回归守卫。
    font_cards = [
        ("lyricFontOriginalCard", "原文歌词字体", 7),
        ("lyricFontTranslationCard", "译文歌词字体", 7),
        ("lyricFontRomanizedCard", "罗马音歌词字体", 6),
        ("lyricFontJapaneseCard", "日语歌词字体", 5),
    ]
    font_selectors = {}
    for name, title, probe_weight in font_cards:
        card = find_object(name)
        if card is None:
            print(f"FAIL: font settings card {name} missing", flush=True)
            return 1
        if card.property("title") != title:
            print(f"FAIL: {name} title={card.property('title')!r} expect {title!r}",
                  flush=True)
            return 1
        desc = card.property("description") or ""
        if len(desc) < 8:
            print(f"FAIL: {name} needs its own description, got {desc!r}", flush=True)
            return 1
        combos = [c for c in card.findChildren(QObject)
                  if "ComboBox" in c.metaObject().className()]
        if len(combos) != 2:
            print(f"FAIL: {name} should host a font + a weight selector, "
                  f"got {len(combos)}", flush=True)
            return 1
        weights = [c for c in combos if c.property("count") == 10]
        fonts = [c for c in combos if c.property("count") != 10]
        if len(weights) != 1 or len(fonts) != 1 or fonts[0].property("count") < 2:
            print(f"FAIL: {name} selectors wrong: "
                  f"counts={[c.property('count') for c in combos]}", flush=True)
            return 1
        font_selectors[name] = (fonts[0], weights[0], probe_weight)
    print("font settings: 4 SettingCards, each with title/description/2 selectors",
          flush=True)

    # 字体/字重选择器读的是同一份共享列表与同一批插件配置键
    for name, (font_combo, weight_combo, probe) in font_selectors.items():
        if weight_combo.property("currentIndex") != 0:
            print(f"FAIL: {name} weight should default to 跟随全局, "
                  f"got {weight_combo.property('currentIndex')}", flush=True)
            return 1
    # 字重写入：激活「Bold」(index 7) → 700（QML 信号从 Python 侧发射）
    from PySide6.QtCore import Q_ARG, QMetaObject, Qt

    romanized_weight = font_selectors["lyricFontRomanizedCard"][1]
    QMetaObject.invokeMethod(romanized_weight, "activated",
                             Qt.ConnectionType.DirectConnection, Q_ARG("int", 7))
    if configs.written.get("lyric_font_weight_romanized") != 700:
        print(f"FAIL: weight selector did not persist, written={configs.written}",
              flush=True)
        return 1
    # 字体写入：激活第 1 项（首项是「跟随全局字体」）→ 应写成具体字体名
    romanized_font = font_selectors["lyricFontRomanizedCard"][0]
    QMetaObject.invokeMethod(romanized_font, "activated",
                             Qt.ConnectionType.DirectConnection, Q_ARG("int", 1))
    expected_family = romanized_font.property("model")[1]
    if configs.written.get("lyric_font_romanized") != expected_family:
        print(f"FAIL: font selector did not persist, written={configs.written}", flush=True)
        return 1
    print("font settings: selectors persist to the plugin config", flush=True)

    # 振假名开关卡：默认开、可写回插件配置（关掉后歌词组件不再渲染假名）
    furigana_card = find_object("lyricFuriganaCard")
    if furigana_card is None:
        print("FAIL: lyricFuriganaCard missing", flush=True)
        return 1
    furigana_switch = [c for c in furigana_card.findChildren(QObject)
                       if "Switch" in c.metaObject().className()]
    if len(furigana_switch) != 1:
        print(f"FAIL: lyricFuriganaCard should host exactly 1 Switch, "
              f"got {len(furigana_switch)}", flush=True)
        return 1
    furigana_switch = furigana_switch[0]
    if not furigana_switch.property("checked"):
        print("FAIL: 振假名 should default to on", flush=True)
        return 1
    # 注意：RinUI Switch 继承 QQuickAbstractButton。Qt 6 里用 setProperty("checked", …)
    # 或 toggle() 都只发 checkedChanged，**不发 toggled**（toggled 只在真实交互
    # 路径上发射），而页面的处理器挂在 onToggled 上。要覆盖真实写回路径，
    # 必须模拟一次鼠标点击，而不是改属性——否则这条断言就是假绿。
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent

    center = furigana_switch.property("width") / 2.0
    mid = furigana_switch.property("height") / 2.0
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(center, mid),
                        QPointF(0, 0), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(center, mid),
                          QPointF(0, 0), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(furigana_switch, press)
    QCoreApplication.sendEvent(furigana_switch, release)
    app.processEvents()
    if configs.written.get("lyric_furigana_enabled") is not False:
        print(f"FAIL: furigana switch did not persist on click, "
              f"written={configs.written}", flush=True)
        return 1
    print("furigana: switch card present, on by default, persists to config", flush=True)

    # 炫酷动画开关卡：默认开、点击后写回配置（关掉后歌词组件回落轻量淡入）
    anim_card = find_object("lyricAnimationCard")
    if anim_card is None:
        print("FAIL: lyricAnimationCard missing", flush=True)
        return 1
    anim_switch = [c for c in anim_card.findChildren(QObject)
                   if "Switch" in c.metaObject().className()]
    if len(anim_switch) != 1:
        print(f"FAIL: lyricAnimationCard should host exactly 1 Switch, "
              f"got {len(anim_switch)}", flush=True)
        return 1
    anim_switch = anim_switch[0]
    if not anim_switch.property("checked"):
        print("FAIL: 炫酷动画 should default to on", flush=True)
        return 1
    # 同振假名：必须模拟鼠标点击才能走到 onToggled 的真实写回路径
    center = anim_switch.property("width") / 2.0
    mid = anim_switch.property("height") / 2.0
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(center, mid),
                        QPointF(0, 0), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(center, mid),
                          QPointF(0, 0), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(anim_switch, press)
    QCoreApplication.sendEvent(anim_switch, release)
    app.processEvents()
    if configs.written.get("lyric_animation_enabled") is not False:
        print(f"FAIL: animation switch did not persist on click, "
              f"written={configs.written}", flush=True)
        return 1
    print("animation: switch card present, on by default, persists to config", flush=True)

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
        "ic_fluent_text_align_left_20_regular",
        "ic_fluent_subtitles_20_regular",
        "ic_fluent_local_language_20_regular",
        "ic_fluent_text_font_20_regular",
        "ic_fluent_slide_transition_20_regular",
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
