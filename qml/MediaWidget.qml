import QtQuick
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
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

    // 背景层（自底向上）：时间水印 → 专辑图双主色渐变 → 播放进度遮罩
    // 圆角跟随框架 cornerRadius（widget_corner_radius 偏好），契合各主题
    backgroundArea: Item {
        id: bgClip
        anchors.fill: parent
        layer.enabled: true
        layer.effect: OpacityMask {
            maskSource: Rectangle {
                width: bgClip.width
                height: bgClip.height
                radius: root.cornerRadius
                color: "black"
            }
        }

        // 时间水印：最粗字重、半透明，贴右下角（圆角裁掉一点边角），放不下时截断
        Text {
            property int timePx: miniMode ? 22 : 40
            Behavior on timePx { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }
            visible: backend && backend.progress > 0
            text: backend ? backend.positionText + "/" + backend.durationText : ""
            color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.22) : Qt.alpha("#000000", 0.15)
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
            font: {
                var f = AppCentral.getQFont(Configs.data.preferences.font, Utils.fontFamily)
                f.pixelSize = timePx
                f.weight = 900
                return f
            }
        }

        // 渐变背景：专辑图两个主色，从左到右淡出
        Rectangle {
            anchors.fill: parent
            visible: backend && backend.art !== ""
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop {
                    position: 0
                    color: Qt.alpha(backend ? backend.accentColor : "#9AA0A6", 0.32)
                }
                GradientStop {
                    position: 1
                    color: Qt.alpha(backend ? backend.accentColor2 : "#9AA0A6", 0.10)
                }
            }
        }

        // 进度遮罩：随播放进度从左向右填充，颜色随明暗模式
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width * (backend ? backend.progress : 0)
            visible: backend && backend.progress > 0
            color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.10) : Qt.alpha("#000000", 0.07)

            Behavior on width {
                NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
            }
        }
    }

    // 主内容：封面 + 标题
    // 不能锚定右侧：框架用 contentArea.childrenRect 计算 implicitWidth，
    // 内容行一旦锚定左右，宽度就会反过来跟随组件，被 header 锁死导致标题截断
    RowLayout {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
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
                    text: qsTr("\u266A")
                    opacity: 0.6
                    font.pixelSize: miniMode ? 12 : 16
                }
            }
        }
        Title {
            id: titleItem
            text: backend ? backend.title : ""
            // 标题自然撑开组件宽度，超过上限才省略
            Layout.maximumWidth: 480
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }
}
