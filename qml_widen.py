"""
运行时撑宽动态通知歌词区（纯内存注入，零文件改动）。

历史版本（<=1.6.1）直接改写 CW2 安装目录的 dynamicNotification.qml，
触发 CW2 的完整性校验导致整个程序拒绝运行（v1.6.2 已删除磁盘补丁）。
本模块改为启动后在 QML 对象树中定位动态通知组件——其根节点带有
notificationTitle 属性（CW2 内部组件，无官方 API 可改宽度）——
把其中 MarqueeTitle（标题栏/歌词栏）的 maximumWidth 提到 480：
能放下的歌词直接静态显示，超宽才跑马灯滚动。

只调用 QObject.setProperty 写内存属性，不触碰磁盘上的任何文件。
MarqueeTitle.implicitWidth 是活绑定，改值后 RowLayout、Widget.implicitWidth
和窗口宽度自动跟随（Widget 上的 Behavior on implicitWidth 还带平滑动画）。
组件重建（切换默认/迷你模式等）后由低频轮询定时器自动重新应用。
"""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from loguru import logger

MAX_WIDTH = 480
_POLL_MS = 3000

# 模块级引用，防止 QTimer 被 Python 垃圾回收
_timer = None


def _has_prop(item: QQuickItem, name: str) -> bool:
    return item.metaObject().indexOfProperty(name) >= 0


def _is_marquee(item: QQuickItem) -> bool:
    # MarqueeTitle 独有接口组合：maximumWidth（宽限定）+ speed（跑马灯速度）
    return _has_prop(item, "maximumWidth") and _has_prop(item, "speed")


def apply_once() -> int:
    """扫描全部窗口，撑宽动态通知中的歌词/标题栏，返回本次修改的对象数。"""
    changed = 0
    for win in QGuiApplication.allWindows():
        # QML Window 声明式子项的 QObject 父级挂在 Window 本身而非
        # contentItem 上，从 Window 整树搜才稳定命中（Loader 加载的子树同样覆盖）
        for item in win.findChildren(QQuickItem):
            # notificationTitle 是 dynamicNotification.qml 根节点的独有属性
            if not _has_prop(item, "notificationTitle"):
                continue
            widened = False
            for marquee in item.findChildren(QQuickItem):
                if _is_marquee(marquee) and marquee.property("maximumWidth") != MAX_WIDTH:
                    marquee.setProperty("maximumWidth", MAX_WIDTH)
                    changed += 1
                    widened = True
            if widened:
                logger.info(
                    f"Media Widgets: dynamic notification lyrics width -> {MAX_WIDTH}px (runtime)"
                )
    return changed


def start() -> None:
    """启动低频轮询：组件晚于插件创建、模式切换重建后都会自动重新应用。"""
    global _timer
    if _timer is not None:
        return
    _timer = QTimer()
    _timer.setInterval(_POLL_MS)
    _timer.timeout.connect(apply_once)
    _timer.start()
    apply_once()


def stop() -> None:
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer = None
