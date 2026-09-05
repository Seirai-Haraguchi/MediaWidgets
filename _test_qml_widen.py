"""qml_widen 冒烟测试：构造模拟 dynamicNotification 结构的窗口，
验证运行时注入只改内存属性——精准命中 MarqueeTitle 形状的目标、
跳过干扰项、幂等，且 start/stop 生命周期不崩。

不依赖 CW2 运行时：QML 结构按 dynamicNotification.qml 的真实接口
（根节点 notificationTitle 属性 + MarqueeTitle 的 maximumWidth/speed/text）搭建。
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem

import qml_widen

# 模拟 dynamicNotification.qml：根节点 + 两个 MarqueeTitle + 两个干扰项
_SCENE = """
import QtQuick

Window {
    visible: false
    width: 600
    height: 200

    Item {
        anchors.fill: parent
        property string notificationTitle: ""
        property string notificationMessage: ""

        // titleLabel：显式 maximumWidth: 150（与 CW2 源码一致）
        Item {
            property int maximumWidth: 150
            property alias text: t1.text
            property int speed: 100
            Text { id: t1; text: "title" }
        }
        // messageLabel：默认 maximumWidth（MarqueeTitle 默认 200）
        Item {
            property int maximumWidth: 200
            property alias text: t2.text
            property int speed: 100
            Text { id: t2; text: "message" }
        }
        // 干扰项：有 maximumWidth 但无 speed，不应被改
        Item { property int maximumWidth: 99 }
        // 干扰项：有 speed 但无 maximumWidth，不应被改
        Item { property int speed: 5 }
    }
}
"""


def _has_prop(item: QQuickItem, name: str) -> bool:
    return item.metaObject().indexOfProperty(name) >= 0


def _max_widths(root: QQuickItem) -> dict:
    """收集根节点下所有带 maximumWidth 属性的项的当前值。"""
    return {
        id(c): c.property("maximumWidth")
        for c in root.findChildren(QQuickItem)
        if _has_prop(c, "maximumWidth")
    }


def main() -> int:
    app = QGuiApplication(sys.argv)
    engine = QQmlEngine()

    # setData 配自定义 URL 会卡在 Loading，走临时文件（设置页测试同款方式）
    scene_file = Path(tempfile.gettempdir()) / "_test_qml_widen_scene.qml"
    scene_file.write_text(_SCENE, encoding="utf-8")
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(scene_file)))
    if component.status() == QQmlComponent.Status.Error:
        print("FAIL: component errors:")
        for e in component.errors():
            print(f"  {e}")
        return 1

    win = component.create()
    if win is None:
        print("FAIL: create() returned None")
        for e in component.errors():
            print(f"  {e}")
        return 1

    # 与 qml_widen.apply_once 同款入口：从 Window 整树搜
    # （QML Window 声明式子项的 QObject 父级在 Window 而非 contentItem）
    items = win.findChildren(QQuickItem)
    roots = [i for i in items if _has_prop(i, "notificationTitle")]
    if len(roots) != 1:
        print(f"FAIL: expected 1 notification root, got {len(roots)}")
        return 1
    root = roots[0]

    before = list(_max_widths(root).values())
    if sorted(before) != [99, 150, 200]:
        print(f"FAIL: unexpected initial widths {before}")
        return 1

    # 首次注入：两个 MarqueeTitle → 480，干扰项保持原值
    changed = qml_widen.apply_once()
    after = _max_widths(root)
    values = sorted(after.values())
    if values != [99, 480, 480]:
        print(f"FAIL: expected [99, 480, 480], got {values}")
        return 1
    if changed != 2:
        print(f"FAIL: expected 2 changed, got {changed}")
        return 1

    # 幂等：再次注入应零修改
    changed_again = qml_widen.apply_once()
    if changed_again != 0:
        print(f"FAIL: idempotency broken, changed {changed_again}")
        return 1

    # 组件重建场景：新窗口（如模式切换后）也应被轮询命中
    win2 = component.create()
    root2 = [
        i for i in win2.findChildren(QQuickItem)
        if _has_prop(i, "notificationTitle")
    ][0]
    if qml_widen.apply_once() != 2:
        w = sorted(_max_widths(root2).values())
        print(f"FAIL: recreated widget not re-widened, widths {w}")
        return 1

    # start/stop 生命周期
    qml_widen.start()
    qml_widen.start()  # 重复调用应幂等（不重复建 timer）
    qml_widen.stop()
    qml_widen.stop()

    print("PASS: runtime widen hits only MarqueeTitle items, idempotent, lifecycle-safe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
