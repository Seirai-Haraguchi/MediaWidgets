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
    property real maxTextWidth: 480

    // 标题测量器（fillWidth 模式下驱动 implicitWidth 实现收缩）
    Text {
        id: titleMeasurer
        visible: false
        text: backend ? backend.title : ""
        font: titleItem.font
    }

    // 宽度 = 封面 + 标题自然宽度（封顶） + 边距；歌名变短时收回，但保留最小宽度
    implicitWidth: Math.max(
        (miniMode ? 24 : 36) + 8 + 120 + 32,   // 最小宽度，保证短歌名也可见
        (miniMode ? 24 : 36) + 8
        + Math.min(titleMeasurer.implicitWidth, root.maxTextWidth)
        + 32
    )

    // 主内容：封面 + 标题，左对齐、撑满组件宽度（fillWidth 保证不会溢出）
    RowLayout {
        id: mainRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 8
        Item {
            Layout.preferredWidth: miniMode ? 24 : 36
            Layout.preferredHeight: miniMode ? 24 : 36
            Image {
                anchors.fill: parent
                source: backend && backend.art !== "" ? backend.art : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                visible: source !== ""
            }
            Rectangle {
                anchors.fill: parent
                radius: miniMode ? 6 : 8
                color: "#1E9AA0A6"
                visible: backend ? backend.art === "" : true
                Text {
                    anchors.centerIn: parent
                    text: qsTr("♪")
                    opacity: 0.6
                    font.pixelSize: miniMode ? 12 : 16
                }
            }
        }
        Title {
            id: titleItem
            Layout.fillWidth: true
            Layout.maximumWidth: root.maxTextWidth
            text: backend ? backend.title : ""
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }
}
