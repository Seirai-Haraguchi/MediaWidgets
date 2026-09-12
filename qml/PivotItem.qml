import QtQuick
import QtQuick.Layouts

// Pivot 的单个页面：text / iconName 供页签头渲染，默认子属性为页面内容列。
// 构建完成后向上寻找宿主 Pivot 注册页签；显隐由宿主按 currentIndex 统一控制，
// 页面常驻（切换不销毁，控件状态得以保留）。
Item {
    id: root

    property string text: ""
    property string iconName: ""
    property real spacing: 4
    default property alias content: contentColumn.data

    // 由宿主 Pivot 注册时填写
    property var __pivot: null
    property int __index: -1

    Layout.fillWidth: true
    visible: __pivot !== null && __pivot.currentIndex === __index
    implicitHeight: contentColumn.implicitHeight

    Component.onCompleted: {
        var host = root.parent
        while (host) {
            if (typeof host.addPage === "function") {
                host.addPage(root)
                break
            }
            host = host.parent
        }
    }
    Component.onDestruction: {
        if (__pivot !== null)
            __pivot.removePage(root)
    }

    ColumnLayout {
        id: contentColumn
        width: root.width
        spacing: root.spacing
    }
}
