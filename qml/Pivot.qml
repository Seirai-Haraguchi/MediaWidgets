import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI

// WinUI 风格 Pivot：页签条 + 单页内容区。宿主 RinUI 未提供 Pivot 组件，
// 这里基于其原生 Segmented 自实现（与设置 → 插件主页的分段页签同款），
// 对外保持 Pivot/PivotItem 写法：
//
//   Pivot {
//       PivotItem {
//           text: qsTr("媒体组件")
//           iconName: "ic_fluent_album_20_regular"
//           // 页面内容作为默认子项直接声明
//       }
//   }
//
// 页面统一挂进内容列，靠可见性切换实现“仅显示当前页”；
// Qt Quick 布局对不可见子项不占位，页高随当前内容自动伸缩。
// 显式 import 的模块优先于同目录类型，宿主未来若提供原生 RinUI.Pivot
// 会自动遮蔽本组件，届时可直接删除这两个文件切换。
ColumnLayout {
    id: root

    default property alias pages: pageHost.data
    // 可写别名：对外等价于 WinUI Pivot.SelectedIndex，可编程切换页签
    property alias currentIndex: tabBar.currentIndex
    readonly property int count: tabBar.count

    // PivotItem 构建完成后向上找到这里注册自身，页签头与页面一一对应
    function addPage(page) {
        // 按页面在声明序列中的位置插入页签头：姊妹项的 Component.onCompleted
        // 触发次序与声明次序相反，若只按调用先后 append，页签顺序会被反转
        var wasDefault = tabBar.count === 0 || tabBar.currentIndex === 0
        var header = headerComponent.createObject(tabBar)
        header.__page = page
        tabBar.insertItem(Math.min(pageOrder(page), tabBar.count), header)
        page.__pivot = root
        reindexPages()
        // 前插会让 TabBar 把 currentIndex 顺移，这里把“默认选中首项”保持住
        if (wasDefault)
            tabBar.currentIndex = 0
    }

    function removePage(page) {
        var removed = -1
        for (var i = 0; i < tabBar.count; i++) {
            var header = tabBar.itemAt(i)
            if (header && header.__page === page) {
                removed = i
                break
            }
        }
        if (removed < 0)
            return
        var target = tabBar.itemAt(removed)
        tabBar.removeItem(target)
        target.destroy()
        page.__pivot = null
        page.__index = -1
        // 移除后重排后续页面的索引，保持页签头与页面对齐
        reindexPages()
    }

    // 声明次序：数出父级 children 中排在 page 之前的页面个数。
    // 不依赖 onCompleted 触发次序，因此页签顺序始终与声明顺序一致。
    function pageOrder(page) {
        var siblings = page.parent ? page.parent.children : null
        if (!siblings)
            return tabBar.count
        var order = 0
        for (var i = 0; i < siblings.length; i++) {
            if (siblings[i] === page)
                return order
            if (isPage(siblings[i]))
                order++
        }
        return tabBar.count
    }

    function isPage(item) {
        return !!item && typeof item.iconName === "string"
               && typeof item.text === "string"
    }

    function reindexPages() {
        for (var i = 0; i < tabBar.count; i++) {
            var header = tabBar.itemAt(i)
            if (header && header.__page)
                header.__page.__index = i
        }
    }

    // 与宿主设置 → 插件主页同一套 Segmented 页签样式（圆角底 + 选中块）
    Segmented {
        id: tabBar
        objectName: "widgetPivotBar"
        Layout.fillWidth: true
    }

    ColumnLayout {
        id: pageHost
        Layout.fillWidth: true
        spacing: 0
    }

    Component {
        id: headerComponent

        SegmentedItem {
            property var __page: null
            text: __page !== null ? __page.text : ""
            icon.name: __page !== null ? __page.iconName : ""
        }
    }
}
