import QtQuick
import QtQuick.Layouts
import RinUI
import ClassWidgets.Theme

Widget {
    id: root
    // header: 有媒体时显示艺人，无媒体时显示占位文字
    text: {
        if (!backend || backend.title === "")
            return qsTr("Media")
        const a = backend.artist
        return a ? a : qsTr("Playing")
    }

    property real coverSize: miniMode ? 24 : 36

    // RowLayout 使用锚点铺满父项时不会自动把自身尺寸传给 Widget。
    // 暴露内容行的自然宽度，避免框架把组件初始收窄到只剩封面；
    // 最终宽度仍由 Class Widgets 的布局策略决定。
    implicitWidth: Math.max(mainRow.implicitWidth + 32, 180)

    // 主内容：封面 + 标题，宽度完全交给 Class Widgets 框架处理（框架自带收窄）
    RowLayout {
        id: mainRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 8
        Item {
            Layout.minimumWidth: root.coverSize
            Layout.preferredWidth: root.coverSize
            Layout.maximumWidth: root.coverSize
            Layout.minimumHeight: root.coverSize
            Layout.preferredHeight: root.coverSize
            Layout.maximumHeight: root.coverSize
            Image {
                anchors.fill: parent
                source: backend && backend.art !== "" ? backend.art : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                visible: source !== ""
            }
            Rectangle {
                anchors.fill: parent
                radius: root.coverSize / 4.5
                color: "#1E9AA0A6"
                visible: backend ? backend.art === "" : true
            }
        }
        MarqueeTitle {
            id: titleItem
            Layout.fillWidth: true
            maximumWidth: 260
            text: backend ? backend.title : ""
            running: true
        }
    }
}
