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
// - 宽度：主行按内容自然撑开组件（480 封顶），副行启用时从其额度中扣掉副行块；
//   不再绑定 root.width（否则内容无法反过来撑宽组件，副行关闭时横向空间浪费）
// - 卡拉OK填充扫描：仅当后端 wordTiming=true（QRC/KRC 逐字）时启用；
//   行级 LRC 只高亮整行，不做填充扫描
// - 超宽跑马灯：逐字跟随演唱边缘；行级按行内进度推进；换行时瞬时归位避免抽搐
// - 前奏期间显示第一行（未填充的暗色预览），唱到后自然开始填充
// - 背景层：仅专辑图双主色渐变；可在插件设置中调整开关与浓度

Widget {
    id: root

    readonly property var media: backend ? backend.media : null
    readonly property bool hasMedia: media && media.title !== ""

    // 歌词组件背景偏好（设置页写入后即时更新）
    readonly property var pluginConfig: {
        var plugins = Configs.data && Configs.data.plugins ? Configs.data.plugins : null
        return plugins && plugins.configs
               ? plugins.configs["com.seiraiharaguchi.mediawidgets"] : null
    }
    readonly property bool gradientBackgroundEnabled: {
        return !pluginConfig || pluginConfig.lyric_gradient_background !== false
    }
    readonly property real gradientIntensity: {
        if (!pluginConfig || pluginConfig.lyric_gradient_intensity === undefined)
            return 1.0
        var value = Number(pluginConfig.lyric_gradient_intensity)
        return isNaN(value) ? 1.0 : Math.max(0, Math.min(100, value)) / 100
    }

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
        function onLineChanged() {
            sweepRow.prepareLineChange()
            linePop.restart()
        }
    }

    // 背景层：专辑图双主色渐变（从左到右淡出），圆角跟随框架 cornerRadius 以契合各主题
    backgroundArea: Rectangle {
        objectName: "gradientBackground"
        anchors.fill: parent
        radius: root.cornerRadius
        visible: root.gradientBackgroundEnabled && root.media && root.media.art !== ""
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop {
                position: 0
                color: Qt.alpha(root.media ? root.media.accentColor : "#9AA0A6",
                                0.32 * root.gradientIntensity)
            }
            GradientStop {
                position: 1
                color: Qt.alpha(root.media ? root.media.accentColor2 : "#9AA0A6",
                                0.10 * root.gradientIntensity)
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
            // 内容驱动撑宽：主行最多 480；副行可见时从其额度扣掉副行块（含分隔线间距），
            // 副行关闭后额度还给主行，组件可横向扩展到满幅可用宽度。
            // 切勿绑定 root.width——会形成「宽度由内容决定、内容上限又跟宽度走」的死锁，
            // 导致副行关闭后主行仍卡在窄视口、只能靠跑马灯硬滚。
            readonly property real secondaryReserve: subLabel.visible ? (subLabel.width + 18) : 0
            // 短行按字宽撑开；长行顶到 maximumWidth 后由跑马灯滚动
            readonly property real mainMaxWidth: Math.max(120, 480 - secondaryReserve)
            Layout.maximumWidth: mainMaxWidth
            clip: true
            words: backend ? backend.words : []
            wordTiming: backend ? backend.wordTiming : false
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
    // 行级歌词关闭填充，整行以 fillColor 显示；超宽时整行向左滚动
    component WordSweep: Item {
        id: sweep
        property var words: []
        property bool wordTiming: false
        property int positionMs: 0
        property color baseColor: "#808080"
        property color fillColor: "#FFFFFF"
        property int pixelSize: 20
        property int fontWeight: 600
        // 换行瞬间关闭滚动 Behavior，避免从上一行缓动造成抽搐/错位
        property bool scrollAnimating: true
        // 实际应用到 wordRow.x；与 scrollX 目标分离，换行时可瞬时吸附
        property real displayedScrollX: 0

        implicitWidth: wordRow.implicitWidth
        implicitHeight: wordRow.implicitHeight

        Behavior on displayedScrollX {
            enabled: sweep.scrollAnimating
            // 短于后端 100ms 节拍，跟随及时且不在两次 tick 间拖尾
            NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
        }

        function prepareLineChange() {
            // 换行总是从行首显示：瞬时归零，避免沿用上一行偏移或 Repeater 抛光前的错误目标
            scrollAnimating = false
            displayedScrollX = 0
            Qt.callLater(function () { sweep.scrollAnimating = true })
        }

        onScrollXChanged: displayedScrollX = scrollX

        // 当前唱到的像素边缘：只统计已唱/正在唱的词（忽略尚未开唱的后续词）
        readonly property real fillEdgeX: {
            var pos = sweep.positionMs
            var edge = 0
            var kids = wordRow.children
            for (var i = 0; i < kids.length; i++) {
                var it = kids[i]
                var w = it.modelData
                if (!w)
                    continue
                if (!sweep.wordTiming) {
                    edge = Math.max(edge, it.x + it.width)
                    continue
                }
                if (pos >= w.endMs)
                    edge = Math.max(edge, it.x + it.width)
                else if (pos > w.startMs)
                    edge = Math.max(edge, it.x + it.width
                                    * (pos - w.startMs) / Math.max(1, w.endMs - w.startMs))
            }
            return edge
        }

        // 跑马灯目标偏移：
        // - 放得下：0
        // - 逐字：演唱边缘锚定在视口约 35% 处，不滚过行尾
        // - 行级：按行起止进度映射到 [0, maxScroll]
        readonly property real scrollX: {
            var maxScroll = Math.max(0, wordRow.implicitWidth - sweep.width)
            if (maxScroll <= 0)
                return 0
            if (!sweep.wordTiming) {
                var w0 = (sweep.words && sweep.words.length) ? sweep.words[0] : null
                if (!w0)
                    return 0
                var span = Math.max(1, w0.endMs - w0.startMs)
                var t = (sweep.positionMs - w0.startMs) / span
                t = Math.max(0, Math.min(1, t))
                return -maxScroll * t
            }
            var anchor = sweep.width * 0.35
            return -Math.max(0, Math.min(maxScroll, fillEdgeX - anchor))
        }

        Row {
            id: wordRow
            spacing: 0
            x: sweep.displayedScrollX

            Repeater {
                model: sweep.words

                delegate: Item {
                    id: wordItem
                    required property var modelData
                    implicitWidth: baseText.width
                    implicitHeight: baseText.height

                    // 已唱比例：无逐字时间戳时整词点亮；有则词内线性推进
                    readonly property real fillRatio: {
                        if (!sweep.wordTiming)
                            return 1.0
                        var w = wordItem.modelData
                        var pos = sweep.positionMs
                        if (pos >= w.endMs) return 1.0
                        if (pos <= w.startMs) return 0.0
                        return (pos - w.startMs) / Math.max(1, w.endMs - w.startMs)
                    }

                    Text {
                        id: baseText
                        text: wordItem.modelData.text
                        // 行级：底层也用满色，避免看起来像卡在唱完态的卡拉OK
                        color: sweep.wordTiming ? sweep.baseColor : sweep.fillColor
                        font.family: root.baseFont.family
                        font.pixelSize: sweep.pixelSize
                        font.weight: sweep.fontWeight
                    }

                    // 卡拉OK顶层裁切：仅逐字模式启用
                    Item {
                        visible: sweep.wordTiming
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: baseText.width * wordItem.fillRatio
                        clip: true
                        Behavior on width {
                            enabled: sweep.wordTiming && sweep.scrollAnimating
                            NumberAnimation { duration: 90; easing.type: Easing.Linear }
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
