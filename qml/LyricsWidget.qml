import QtQuick
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import ClassWidgets.Theme

// 注意：不要 import RinUI —— 它导出的 Text 会遮蔽 QtQuick 原生 Text，
// 其默认 wrapMode: WordWrap 会让无显式宽度的歌词文本 implicitWidth 塌缩为 ~1px

// 逐字歌词小组件：布局语言与 MediaWidget 一致（封面 + 双主色渐变 + 进度遮罩 + 时间水印）
// - 当前行卡拉OK填充扫描：逐字歌词（QRC/KRC）按词填充，行级歌词（LRC）整行一个"词"，同一套动画
// - 副行：有翻译且开启翻译 → 译文；否则显示下一行歌词预览（最后一行时留空）
// - 前奏期间显示第一行（未填充的暗色预览），唱到后自然开始填充
// - 不设 header（text 留空）：两行文字需要完整内容区高度
Widget {
    id: root

    readonly property var media: backend ? backend.media : null
    readonly property bool hasMedia: media && media.title !== ""
    readonly property int maxContentWidth: 480
    // 卡拉OK双色：已唱满色、未唱半透明；主文字色不用专辑主色，保证任何封面下都可读
    readonly property color sungColor: Theme.isDark() ? "#FFFFFF" : "#1B1B1B"
    readonly property color unsungColor: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.40) : Qt.alpha("#000000", 0.40)
    readonly property color transColor: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.62) : Qt.alpha("#000000", 0.60)
    readonly property color nextColor: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.38) : Qt.alpha("#000000", 0.38)

    // CW2 Text.qml 同款字体方式：QFont 整对象赋值在 PySide6 下会丢子属性，
    // 必须拆成 family/pixelSize/weight 子属性分别绑定
    readonly property var baseFont: AppCentral.getQFont(Configs.data.preferences.font, Utils.fontFamily)

    text: ""

    // 换行时轻微淡入，突出逐字扫描主体
    NumberAnimation {
        id: linePop
        target: lyricColumn
        property: "opacity"
        from: 0.35
        to: 1
        duration: 260
        easing.type: Easing.OutQuad
    }

    Connections {
        target: root.backend
        function onLineChanged() { linePop.restart() }
    }

    // 背景层（自底向上）：时间水印 → 专辑图双主色渐变 → 播放进度遮罩
    backgroundArea: Item {
        id: bgClip
        anchors.fill: parent
        layer.enabled: true
        layer.effect: OpacityMask {
            maskSource: Rectangle {
                width: bgClip.width
                height: bgClip.height
                radius: bgClip.height * 0.22
                color: "black"
            }
        }

        Text {
            property int timePx: miniMode ? 22 : 40
            Behavior on timePx { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }
            visible: root.media && root.media.progress > 0
            text: root.media ? root.media.positionText + "/" + root.media.durationText : ""
            color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.22) : Qt.alpha("#000000", 0.15)
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
            font.family: root.baseFont.family
            font.pixelSize: timePx
            font.weight: 900
        }

        Rectangle {
            anchors.fill: parent
            visible: root.media && root.media.art !== ""
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop {
                    position: 0
                    color: Qt.alpha(root.media ? root.media.accentColor : "#9AA0A6", 0.32)
                }
                GradientStop {
                    position: 1
                    color: Qt.alpha(root.media ? root.media.accentColor2 : "#9AA0A6", 0.10)
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width * (root.media ? root.media.progress : 0)
            visible: root.media && root.media.progress > 0
            color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.10) : Qt.alpha("#000000", 0.07)

            Behavior on width {
                NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
            }
        }
    }

    // 主内容：封面 + 歌词两行
    // 与 MediaWidget 相同：不能锚定右侧，内容行自然撑开组件宽度，超上限由内层裁切兜底
    RowLayout {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: 10

        Item {
            Layout.preferredWidth: miniMode ? 24 : 40
            Layout.preferredHeight: miniMode ? 24 : 40
            Image {
                anchors.fill: parent
                source: root.hasMedia ? root.media.art : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                visible: source !== ""
            }
            Rectangle {
                anchors.fill: parent
                radius: miniMode ? 6 : 9
                color: "#1E9AA0A6"
                visible: !root.hasMedia || root.media.art === ""
                Text {
                    anchors.centerIn: parent
                    text: qsTr("\u266A")
                    opacity: 0.6
                    font.pixelSize: miniMode ? 12 : 18
                }
            }
        }

        ColumnLayout {
            id: lyricColumn
            spacing: miniMode ? 0 : 3

            // 当前行：状态文案 与 逐字扫描 二选一
            Item {
                id: lineClip
                Layout.maximumWidth: root.maxContentWidth
                implicitWidth: Math.min(
                    statusText.visible ? statusText.implicitWidth : sweepRow.implicitWidth,
                    root.maxContentWidth)
                implicitHeight: statusText.visible ? statusText.implicitHeight : sweepRow.implicitHeight
                clip: true
                // 超宽时右侧渐隐而不是硬切
                layer.enabled: sweepRow.visible && sweepRow.implicitWidth > lineClip.width
                layer.effect: OpacityMask {
                    maskSource: Rectangle {
                        width: lineClip.width
                        height: lineClip.height
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "#FF000000" }
                            GradientStop {
                                position: Math.max(0.0, 1 - 30 / Math.max(1, lineClip.width))
                                color: "#FF000000"
                            }
                            GradientStop { position: 1; color: "#00000000" }
                        }
                    }
                }

                Text {
                    id: statusText
                    visible: !root.backend || root.backend.state !== "ready"
                    text: {
                        if (!root.backend)
                            return ""
                        if (!root.hasMedia)
                            return qsTr("未在播放")
                        switch (root.backend.state) {
                        case "loading": return qsTr("正在获取歌词…")
                        case "nomatch": return qsTr("未找到这首歌的歌词")
                        case "error": return qsTr("歌词获取失败")
                        default: return ""
                        }
                    }
                    color: root.unsungColor
                    font.family: root.baseFont.family
                    font.pixelSize: miniMode ? 14 : 17
                    font.weight: 500
                }

                WordSweep {
                    id: sweepRow
                    visible: !statusText.visible
                    words: root.backend ? root.backend.words : []
                    positionMs: root.backend ? root.backend.positionMs : 0
                    baseColor: root.unsungColor
                    fillColor: root.sungColor
                    pixelSize: miniMode ? 15 : 20
                    fontWeight: miniMode ? 600 : 700
                }
            }

            // 副行：译文更亮一些，下一行预览更暗
            Text {
                id: subText
                Layout.maximumWidth: root.maxContentWidth
                visible: !miniMode
                text: root.backend ? root.backend.subLine : ""
                color: root.backend && root.backend.subIsTranslation
                       ? root.transColor : root.nextColor
                elide: Text.ElideRight
                font.family: root.baseFont.family
                font.pixelSize: 13
                font.weight: 400
            }
        }
    }

    // 逐字卡拉OK行：底层未唱文字 + 顶层已唱文字按词宽裁切，随 positionMs 填充
    component WordSweep: Item {
        id: sweep
        property var words: []
        property int positionMs: 0
        property color baseColor: "#808080"
        property color fillColor: "#FFFFFF"
        property int pixelSize: 20
        property int fontWeight: 700

        implicitWidth: wordRow.implicitWidth
        implicitHeight: wordRow.implicitHeight

        Row {
            id: wordRow
            spacing: 0

            Repeater {
                model: sweep.words

                delegate: Item {
                    id: wordItem
                    required property var modelData
                    implicitWidth: baseText.width
                    implicitHeight: baseText.height

                    // 已唱比例：词内线性推进，唱完为 1
                    readonly property real fillRatio: {
                        var w = wordItem.modelData
                        var pos = sweep.positionMs
                        if (pos >= w.endMs) return 1.0
                        if (pos <= w.startMs) return 0.0
                        return (pos - w.startMs) / Math.max(1, w.endMs - w.startMs)
                    }

                    Text {
                        id: baseText
                        text: wordItem.modelData.text
                        color: sweep.baseColor
                        font.family: root.baseFont.family
                        font.pixelSize: sweep.pixelSize
                        font.weight: sweep.fontWeight
                    }

                    Item {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: baseText.width * wordItem.fillRatio
                        clip: true
                        // 与后端 100ms 节拍同长的线性插值 → 连续扫描
                        Behavior on width {
                            NumberAnimation { duration: 100; easing.type: Easing.Linear }
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            text: wordItem.modelData.text
                            color: sweep.fillColor
                            font.family: root.baseFont.family
                            font.pixelSize: sweep.pixelSize
                            font.weight: sweep.fontWeight
                        }
                    }
                }
            }
        }
    }
}
