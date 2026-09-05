import ClassWidgets.Theme   // Widget / Title / MarqueeTitle；须先于 QtQuick 导入
import QtQuick              // 后导入：同名冲突后者优先，保证 Text 解析为 QtQuick 原生 Text
import QtQuick.Layouts
import RinUI as Rin         // 限定名导入：只用 Theme/Utils 单例，避免其 Text 遮蔽原生 Text

// 注意：不要非限定 import RinUI，也不要让 ClassWidgets.Theme 晚于 QtQuick 导入 ——
// 两者导出的 Text（默认 wrapMode: WordWrap）都会遮蔽 QtQuick 原生 Text，
// 让无显式宽度的歌词文本 implicitWidth 塌缩为 ~1px
// Theme/Utils 是 RinUI 模块的单例（ClassWidgets.Theme 并不导出它们），
// 因此用 Rin.Theme / Rin.Utils 访问，保证真实 CW2 运行时可解析

// 逐字歌词小组件：对齐 Class Widgets 2 设计语言，与 MediaWidget 同一套约定
// - header（副标题）：歌名 / Lyrics，与 CW2 内置组件的副标题位置一致
// - 主行（当前行 / 状态文案）：Title 标尺（正常 28 / mini 20，px 带 400ms 过渡动画），
//   字重跟随用户偏好 Configs.data.preferences.font_weight，不再硬编码
// - 副行（译文 / 下一句预览）：dynamicNotification 同款行内双文本模式，
//   用框架 MarqueeTitle（超宽自动跑马灯滚动），mini 模式隐藏
// - 宽度交给框架：视口随组件宽度自适应（扣掉副行块，480 封顶）；行宽超视口时
//   不再硬切，而是整行向左滚动（跑马灯跟随逐字演唱位置，行内唱完自动归位）
// - 卡拉OK填充扫描：逐字歌词（QRC/KRC）按词填充，行级歌词（LRC）整行一个词，同一套动画
// - 前奏期间显示第一行（未填充的暗色预览），唱到后自然开始填充
// - 背景层：仅专辑图双主色渐变；不显示进度数字、进度遮罩与封面图

Widget {
    id: root

    readonly property var media: backend ? backend.media : null
    readonly property bool hasMedia: media && media.title !== ""

    // 与 CW2 Title 同标尺：正常 28、mini 20，切换时 400ms 过渡（Title.qml 同款动画）
    property int titlePx: miniMode ? 20 : 28
    Behavior on titlePx { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }

    // 字重跟随用户偏好（Title/Subtitle 的取值方式），不再硬编码 700
    readonly property int titleWeight: Configs.data.preferences.font_weight || 600

    // CW2 Text.qml 同款字体方式：QFont 整对象赋值在 PySide6 下会丢子属性，
    // 必须拆成 family/pixelSize/weight 子属性分别绑定
    readonly property var baseFont: AppCentral.getQFont(Configs.data.preferences.font, Rin.Utils.fontFamily)

    // 卡拉OK双色：已唱满色、未唱半透明；主文字色不用专辑主色，保证任何封面下都可读
    readonly property color sungColor: Rin.Theme.isDark() ? "#FFFFFF" : "#1B1B1B"
    readonly property color unsungColor: Rin.Theme.isDark() ? Qt.alpha("#FFFFFF", 0.40) : Qt.alpha("#000000", 0.40)

    // header 副标题与 MediaWidget 同位置：有媒体显歌名，无媒体显组件名
    text: backend && hasMedia ? media.title : qsTr("Lyrics")

    // 换行时轻微淡入，突出逐字扫描主体
    NumberAnimation {
        id: linePop
        target: sweepRow
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

    // 背景层：专辑图双主色渐变（从左到右淡出），圆角跟随框架 cornerRadius 以契合各主题
    backgroundArea: Rectangle {
        anchors.fill: parent
        radius: root.cornerRadius
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

    // 主内容：当前行 | 副行（dynamicNotification 的行内双文本模式）
    // 与 MediaWidget 相同：不能锚定右侧，内容行自然撑开组件宽度，超上限由框架裁切兜底
    RowLayout {
        id: contentRow
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        // 当前行：状态文案 与 逐字扫描 二选一，同为 Title 标尺
        // 状态文案用框架 Title（CW2 内置组件的占位写法，如 Nothing right now）
        Title {
            id: statusText
            visible: !backend || backend.state !== "ready"
            text: {
                if (!backend)
                    return ""
                if (!root.hasMedia)
                    return qsTr("未在播放")
                switch (backend.state) {
                case "loading": return qsTr("正在获取歌词…")
                case "nomatch": return qsTr("未找到这首歌的歌词")
                case "error": return qsTr("歌词获取失败")
                default: return ""
                }
            }
            color: root.unsungColor
        }

        WordSweep {
            id: sweepRow
            visible: !statusText.visible
            // 视口随组件宽度走（扣掉副行块，480 封顶、120 兜底）：
            // 行宽超出视口时组件不再被撑宽，由 WordSweep 跑马灯跟随滚动
            Layout.maximumWidth: Math.max(120, Math.min(480, root.width - root.padding * 2
                - (subLabel.visible ? subLabel.width + 18 : 0)))
            clip: true
            words: backend ? backend.words : []
            positionMs: backend ? backend.positionMs : 0
            baseColor: root.unsungColor
            fillColor: root.sungColor
            pixelSize: root.titlePx
            fontWeight: root.titleWeight
        }

        // 正文与副文本之间的 2px 分隔线（dynamicNotification 同款）
        Rectangle {
            visible: subLabel.visible
            Layout.preferredWidth: 2
            Layout.leftMargin: 4
            Layout.rightMargin: 4
            Layout.fillHeight: true
            color: Rin.Theme.isDark() ? Qt.alpha("#FFFFFF", 0.28) : Qt.alpha("#000000", 0.18)
        }

        // 副行：译文更亮、下一句预览更暗；MarqueeTitle 超宽自动跑马灯
        MarqueeTitle {
            id: subLabel
            visible: !miniMode && sweepRow.visible && text !== ""
            text: backend ? backend.subLine : ""
            maximumWidth: 200
            speed: 100
            opacity: backend && backend.subIsTranslation ? 0.62 : 0.38
        }
    }

    // 逐字卡拉OK行：底层未唱文字 + 顶层已唱文字按词宽裁切，随 positionMs 填充；
    // 行宽超出视口时整行向左滚动（跑马灯跟随演唱位置），行宽放得下时静止
    component WordSweep: Item {
        id: sweep
        property var words: []
        property int positionMs: 0
        property color baseColor: "#808080"
        property color fillColor: "#FFFFFF"
        property int pixelSize: 20
        property int fontWeight: 600

        implicitWidth: wordRow.implicitWidth
        implicitHeight: wordRow.implicitHeight

        // 当前唱到的像素边缘（行内坐标）：已唱词计整宽，正在唱的词按比例推进
        readonly property real fillEdgeX: {
            var pos = sweep.positionMs
            var edge = 0
            var kids = wordRow.children
            for (var i = 0; i < kids.length; i++) {
                var it = kids[i]
                var w = it.modelData
                if (!w)
                    continue
                var frac = pos >= w.endMs ? 1.0
                         : pos <= w.startMs ? 0.0
                         : (pos - w.startMs) / Math.max(1, w.endMs - w.startMs)
                edge = Math.max(edge, it.x + it.width * frac)
            }
            return edge
        }

        // 跑马灯跟随：唱到边缘锚定在视口 30% 处向左滚，行宽放得下时不动，且不滚过行尾
        readonly property real scrollX: {
            var maxScroll = Math.max(0, wordRow.implicitWidth - sweep.width)
            return -Math.max(0, Math.min(maxScroll, fillEdgeX - sweep.width * 0.3))
        }

        Row {
            id: wordRow
            spacing: 0
            x: sweep.scrollX
            Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutQuad } }

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
