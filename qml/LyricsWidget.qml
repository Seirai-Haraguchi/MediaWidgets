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
// - 振假名（ruby）：仅 QQ QRC 的 [kana:] 提供数据。汉字的平假名注音以小字画在
//   主字上方（0.42 倍字号），与主字同色同填充进度；开关由设置页控制，
//   无假名数据时行高不额外增加
// - 日语独立字体：仅对含假名的日语歌词行（及假名注音）生效，
//   跟随全局设置时回落到原文字体
// - 长音辉光：参考 MediaIsland / AMLL，仅逐字长音（>1000ms）启用，行级绝不套用
// - 间奏显示：参考 MediaIsland 的 InterludeDotsPresenter——相邻两行之间存在
//   ≥4s 的长空档（含开头前奏）时，主行换成三个共享基线、依次点亮的呼吸点；
//   间奏末尾 250ms 由后端提前切到下一句预览，收尾不回落上一句
// - 无可用歌词时不再把组件从布局里抹掉：对齐 CW2 动态通知的空状态写法——
//   宽度归零 + 不可见 + 进出场淡入淡出，组件本身始终留在宿主组件列表里
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

    // 有可用歌词 / 正在搜索 / 编辑模式 → 显示；nomatch/error/idle 才隐藏
    // loading 不算「无歌词」，防止搜索过程中组件闪烁消失
    readonly property bool lyricsUsable: backend && backend.state === "ready"
    readonly property bool lyricsLoading: backend && backend.state === "loading"
    readonly property bool shouldShow: lyricsUsable || lyricsLoading || editMode

    // 当前是否处于间奏：主行换成呼吸点（后端只在「有文档且落在长空档内」时为真）
    readonly property bool interludeActive: backend !== null
                                            && backend.state === "ready" && backend.interlude

    // 隐藏行为对齐 CW2 动态通知组件的空状态：组件始终留在宿主组件列表里
    // （注册、顺序、位置、配置都原样保留），只是宽度归零 + 不可见，
    // 有效歌词回来时自动恢复，不需要重新登记或手动还原。
    // 刻意不再把 height / implicitWidth 绑成 0：那会让组件在宿主 Flow 里连不可见的
    // 占位都不剩，还会把同列第一个组件的 height（以及「添加」按钮的高度）一并带成 0。
    property bool actualVisible: true
    visible: actualVisible
    width: actualVisible ? implicitWidth : 0

    function applyVisibility() {
        if (shouldShow) {
            exitAnim.stop()
            if (!actualVisible)
                actualVisible = true
            enterAnim.restart()
        } else {
            enterAnim.stop()
            exitAnim.restart()
        }
    }
    onShouldShowChanged: applyVisibility()
    Component.onCompleted: {
        actualVisible = shouldShow
        // 记录初始状态，作为「换歌」判定的起点（见 previousState 注释）
        previousState = backend ? backend.state : ""
    }

    // 入场：先归零一帧再淡入 / 轻微放大，避免原生出现造成生硬跳变
    SequentialAnimation {
        id: enterAnim
        NumberAnimation {
            target: root
            property: "opacity"
            from: 0
            to: 0
            duration: 1
        }
        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "opacity"
                from: 0
                to: 1
                duration: 300
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                target: root
                property: "scale"
                from: 0.8
                to: 1
                duration: 400
                easing.type: Easing.OutBack
            }
        }
        onFinished: {
            if (!root.shouldShow)
                root.actualVisible = false
        }
    }

    // 退场：淡出 + 轻微缩小，播完才真正隐藏，保证与「恢复显示」不会互相打架
    SequentialAnimation {
        id: exitAnim
        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "opacity"
                from: 1
                to: 0
                duration: 200
                easing.type: Easing.InQuad
            }
            NumberAnimation {
                target: root
                property: "scale"
                from: 1
                to: 0.9
                duration: 250
                easing.type: Easing.InQuad
            }
        }
        onFinished: {
            if (!root.shouldShow) {
                root.actualVisible = false
                root.scale = 1
            }
        }
    }

    // 与 CW2 Title 同标尺：正常 28、mini 20，切换时 400ms 过渡（Title.qml 同款动画）
    property int titlePx: miniMode ? 20 : 28
    Behavior on titlePx { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }

    // 字重跟随用户偏好（Title/Subtitle 的取值方式），不再硬编码 700
    readonly property int globalFontWeight: Configs.data.preferences.font_weight || 600

    // CW2 Text.qml 同款字体方式：QFont 整对象赋值在 PySide6 下会丢子属性，
    // 必须拆成 family/pixelSize/weight 子属性分别绑定
    readonly property var baseFont: AppCentral.getQFont(Configs.data.preferences.font, Rin.Utils.fontFamily)

    function _fontFollowsGlobal(value) {
        if (value === undefined || value === null)
            return true
        var s = ("" + value).trim()
        return s === "" || s === "Follow global font" || s === qsTr("跟随全局字体")
    }

    function _weightFollowsGlobal(value) {
        var n = Number(value)
        return value === undefined || value === null || isNaN(n) || n <= 0
    }

    readonly property string originalFontFamily: {
        var f = pluginConfig ? pluginConfig.lyric_font_original : ""
        return _fontFollowsGlobal(f) ? baseFont.family : f
    }
    readonly property int originalFontWeight: {
        var w = pluginConfig ? pluginConfig.lyric_font_weight_original : 0
        return _weightFollowsGlobal(w) ? globalFontWeight : Math.round(Number(w))
    }
    readonly property string translationFontFamily: {
        var f = pluginConfig ? pluginConfig.lyric_font_translation : ""
        return _fontFollowsGlobal(f) ? baseFont.family : f
    }
    readonly property int translationFontWeight: {
        var w = pluginConfig ? pluginConfig.lyric_font_weight_translation : 0
        return _weightFollowsGlobal(w) ? globalFontWeight : Math.round(Number(w))
    }
    // 日语独立字体：仅作用于含假名的日语歌词行（及假名注音）
    readonly property string japaneseFontFamily: {
        var f = pluginConfig ? pluginConfig.lyric_font_japanese : ""
        return _fontFollowsGlobal(f) ? "" : f
    }
    readonly property int japaneseFontWeight: {
        var w = pluginConfig ? pluginConfig.lyric_font_weight_japanese : 0
        return _weightFollowsGlobal(w) ? globalFontWeight : Math.round(Number(w))
    }
    // 振假名总开关：关闭后即使歌词带 [kana:] 数据也不显示
    readonly property bool furiganaEnabled: pluginConfig
                                           ? pluginConfig.lyric_furigana_enabled !== false
                                           : true
    // 炫酷动画总开关：关闭后行切换 / 换歌回落到轻量淡入（低配机器或不喜欢大幅动效）
    readonly property bool lyricAnimationsEnabled: pluginConfig
                                                   ? pluginConfig.lyric_animation_enabled !== false
                                                   : true

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

    // ---- 歌词行切换动画 ----
    // 设计取向「炫酷 / 灵动 / 大幅度」：旧实现只有 260ms 的透明度 0.35→1，
    // 幅度太小几乎看不出是一次换行。新实现把「一次换行」拆成四层同时发生：
    //   1) 逐词错峰入场：每个词自带 delay，从下方 34% 行高、1.32 倍缩放入场，
    //      速度归零回弹（opacity lerp 用同一 Easing.OutBack，避免迟到的词只是淡入）
    //   2) 起步模糊：刚入场的词先上模糊再归零，给出「运动模糊」的速度感
    //   3) 横向扫掠：一行高光从左到右扫过，划出换行方向
    //   4) 整体呼吸：行内统一做一次轻微 overshoot 缩放（整行统一，不逐词算，
    //      否则同行主字会参差——与振假名占位同一条铁律）
    // 逐词与扫掠都由 lineSweepPulse 驱动：它是一条 0→1 的归一化进度，
    // Connections.onLineChanged 重新 start() 时会把所有从属动画一并归零重启。
    // 关闭「炫酷动画」时 pulseDuration 变成 1ms 且入场进度立刻归 1，
    // 各层瞬间落到终态，等价于旧版的纯淡入行为。
    property real lineSweepPulse: 1

    // 进度驱动器：把 root.lineSweepPulse 从 0 缓动到 1。
    // 注意 id 绝不能也叫 lineSweepPulse —— QML 里 id 的作用域优先级高于属性名，
    // 同名会让函数体里的 lineSweepPulse 解析成这个动画对象（数字运算得到 NaN，
    // 入场位移与缩放全部失效且不报任何错）。故 id 用 lineSweepPulseAnim。
    NumberAnimation {
        id: lineSweepPulseAnim
        target: root
        property: "lineSweepPulse"
        from: 0
        to: 1
        duration: root.lyricAnimationsEnabled ? 760 : 1
        easing.type: root.lyricAnimationsEnabled ? Easing.OutCubic : Easing.Linear
    }

    // 单词入场进度：delay 单位 ms，span 为单个词的入场时长
    function wordEnterProgress(index, delay, span) {
        if (!lyricAnimationsEnabled)
            return 1
        var elapsed = lineSweepPulse * lineSweepPulseDuration - delay
        if (elapsed <= 0)
            return 0
        return Math.max(0, Math.min(1, elapsed / span))
    }

    // 速度归零的过冲缓出：用于逐词落地的回弹（约 1.7% 过冲后收回）
    function easeOutBack(progress) {
        var p = Math.max(0, Math.min(1, progress))
        var factor = 1.70158
        var shifted = p - 1
        return 1 + (factor + 1) * Math.pow(shifted, 3)
               + factor * Math.pow(shifted, 2)
    }

    readonly property int lineSweepPulseDuration: lyricAnimationsEnabled ? 760 : 1
    // 逐词错峰间距：词多时自动压缩，整行入场不会拖到下一句都唱上了才播完
    readonly property int wordStaggerMs: {
        var n = (sweepRow.words && sweepRow.words.length) ? sweepRow.words.length : 1
        return Math.max(24, Math.min(70, Math.round(520 / Math.max(1, n))))
    }

    // 换行扫掠高光：从左到右扫过整行，位置由 lineSweepPulse 驱动
    Rectangle {
        id: lineSweepHighlight
        objectName: "lineSweepHighlight"
        parent: root
        visible: root.lyricAnimationsEnabled && root.lineSweepPulse < 1 && sweepRow.visible
        width: Math.max(0, sweepRow.width)
        height: 2
        radius: 1
        color: root.sungColor
        opacity: visible ? 0.5 * Math.sin(Math.PI * Math.min(1, Math.max(0, root.lineSweepPulse))) : 0
        x: sweepRow.x + (root.lyricAnimationsEnabled
                         ? (root.lineSweepPulse * 2 - 1) * sweepRow.width
                         : 0)
        y: sweepRow.y + sweepRow.height / 2

        Behavior on opacity {
            NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
        }
    }

    // 换歌：整组件扫过——旧内容向右抖出，新内容从左侧大幅滑入，再回弹归位。
    // 之所以放在 root 上而不是逐元素：换歌是「整块内容重来」，逐元素做反而碎。
    // 不动 scale（规模外扩会顶到宿主布局），只用水平位移 + 透明度，
    // 幅度取组件宽度的 22%，比换行长距离的滑入更明显。
    SequentialAnimation {
        id: songSweepAnim
        NumberAnimation {
            target: root
            property: "songSlideX"
            from: 0
            to: root.lyricAnimationsEnabled ? root.width * 0.16 : 0
            duration: root.lyricAnimationsEnabled ? 170 : 1
            easing.type: Easing.InCubic
        }
        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "songSlideX"
                from: root.lyricAnimationsEnabled ? root.width * 0.16 : 0
                to: root.lyricAnimationsEnabled ? -root.width * 0.22 : 0
                duration: root.lyricAnimationsEnabled ? 340 : 1
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                target: root
                property: "songSlideOpacity"
                from: root.lyricAnimationsEnabled ? 0.0 : 1
                to: 1
                duration: root.lyricAnimationsEnabled ? 340 : 1
                easing.type: Easing.OutCubic
            }
        }
        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "songSlideX"
                from: root.lyricAnimationsEnabled ? -root.width * 0.22 : 0
                to: 0
                duration: root.lyricAnimationsEnabled ? 420 : 1
                easing.type: Easing.OutBack
            }
            NumberAnimation {
                target: root
                property: "songSlideOpacity"
                from: 1
                to: 1
                duration: root.lyricAnimationsEnabled ? 420 : 1
            }
        }
        onFinished: {
            // 必须显式复位：songSweeping 只在动画期间为 true，
            // 否则下一次换歌的重入判定会一直被挡住（曾因此第二次换歌不再播放）。
            root.songSweeping = false
            root.songSlideX = 0
            root.songSlideOpacity = 1
        }
    }

    // 内容层水平位移与不透明度：仅供换歌动画驱动，静息值为 0 / 1
    property real songSlideX: 0
    property real songSlideOpacity: 1
    property bool songSweeping: false

    onLyricAnimationsEnabledChanged: {
        // 关掉时把动画留下的中间态立刻归位，否则会停在歪斜/半透明上
        if (!lyricAnimationsEnabled) {
            songSweepAnim.stop()
            songSweeping = false
            songSlideX = 0
            songSlideOpacity = 1
            root.lineSweepPulse = 1
        }
    }

    // 换歌识别：后端 _on_song_changed 的第一件事是把 state 从 "ready" 归到 "idle"
    // （随后立刻转 loading）。这条 ready → idle 的**下降沿**就是换歌信号：
    // 首次加载、重试、改歌词源都不会从 ready 掉到 idle，因此不会误播。
    // 注意 previousState 存的是「本次 event 携带的新状态」，所以判定必须
    // 在 previousState 变为 "idle" 时触发，而不是变为 "ready" 时。
    property string previousState: ""
    onPreviousStateChanged: {
        if (previousState === "idle" && lastReadyState && root.lyricAnimationsEnabled) {
            songSweepAnim.stop()
            songSlideX = 0
            songSlideOpacity = 0
            songSweeping = true
            songSweepAnim.start()
        }
        lastReadyState = (previousState === "ready")
    }
    // 上一次收到的状态是否为 ready；用来把 ready→idle 与「启动期的 idle」区分开
    property bool lastReadyState: false

    Connections {
        target: root.backend
        function onStateChanged() {
            root.previousState = root.backend ? root.backend.state : ""
        }
        function onLineChanged() {
            sweepRow.prepareLineChange()
            if (root.lyricAnimationsEnabled) {
                lineSweepPulseAnim.stop()
                root.lineSweepPulse = 0
                lineSweepPulseAnim.start()
            } else {
                linePop.restart()
            }
        }
    }

    // 背景层：专辑图双主色渐变（从左到右淡出），圆角跟随框架 cornerRadius 以契合各主题
    backgroundArea: Rectangle {
        objectName: "gradientBackground"
        anchors.fill: parent
        radius: root.cornerRadius
        visible: root.shouldShow && root.gradientBackgroundEnabled
                 && root.media && root.media.art !== ""
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
    // 注意：contentRow 有 anchors.left，锚点会**覆盖 x 属性**，写 x 做位移动画无效。
    // 换歌横扫必须走 transform（锚点管不到 transform），与逐词入场的位移同一处理。
    RowLayout {
        id: contentRow
        objectName: "contentRow"
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        visible: root.shouldShow

        // 换歌时整块内容横扫：translate 位移 + 淡入，静息时回到 0 / 1，对常规布局零影响。
        // 不用 x / width / height —— 锚点会吃掉 x，而宽度受框架收窄逻辑约束，都不参与动画。
        opacity: root.songSlideOpacity
        transform: Translate { x: root.songSlideX }

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

        // 换行时字从下方大幅滑入（幅度大、回弹足），旧版只有 0.35→1 的淡入。
        // contentRow 是 verticalCenter：这里给 WordSweep 加位移不会改变行高，
        // 副行与那条 2px 分隔线不会被带着走（与「隐藏只归零宽度、绝不归零高度」同一约束）。
        WordSweep {
            id: sweepRow
            visible: !statusText.visible && !root.interludeActive
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
            fontFamily: root.originalFontFamily
            fontWeight: root.originalFontWeight
            lineIsJapanese: backend ? backend.lineIsJapanese : false
            furiganaEnabled: root.furiganaEnabled
            japaneseFontFamily: root.japaneseFontFamily
            japaneseFontWeight: root.japaneseFontWeight

            // 整体呼吸缩放：整行一个值（取自算力最省的「全行入场均值」），
            // 不逐词算——逐词缩放会让同行各词大小不一，观感像渲染错误。
            // 换行后只做一次 1.05 → 1 的回落，随后恒为 1，不影响卡拉OK 扫描。
            // 注意：不能用 baseText.height（首帧还未布局，会得到 NaN 并把整个
            // delegate 的 scale 污染成 NaN，入场动画直接消失）。
            readonly property real lineEnterScale: {
                if (root.lineSweepPulse >= 1)
                    return 1
                if (!root.lyricAnimationsEnabled)
                    return 1
                var p = root.lineSweepPulse
                // 起步略过冲再回落，给出「弹一下」的灵动感
                return 1 + 0.05 * Math.sin(Math.PI * Math.min(1, p * 1.15))
            }
            transformOrigin: Item.Center
            scale: lineEnterScale
        }

        // 间奏：三个呼吸点占住主行的位置，间奏结束后换回下一句歌词
        InterludeDots {
            id: interludeDots
            objectName: "interludeDots"
            visible: root.interludeActive
            startMs: backend ? backend.interludeStartMs : 0
            endMs: backend ? backend.interludeEndMs : 0
            positionMs: backend ? backend.positionMs : 0
            color: root.sungColor
            pixelSize: root.titlePx
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
        // 回退到原文/下一句时仍用原文字体设置（仅真实译文走译文字体）
        MarqueeTitle {
            id: subLabel
            visible: !miniMode && sweepRow.visible && text !== ""
            text: backend ? backend.subLine : ""
            maximumWidth: 200
            speed: 100
            opacity: backend && backend.subIsTranslation ? 0.62 : 0.38
            font.family: backend && backend.subIsTranslation
                         ? root.translationFontFamily : root.originalFontFamily
            font.weight: backend && backend.subIsTranslation
                         ? root.translationFontWeight : root.originalFontWeight
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
        property string fontFamily: ""
        property int fontWeight: 600
        // 日语独立字体：仅当整行含假名（lineIsJapanese）且行内有 ruby 时套用
        property string japaneseFontFamily: ""
        property int japaneseFontWeight: 600
        property bool lineIsJapanese: false
        property bool furiganaEnabled: false

        // 该词是否有可显示的振假名（开关开 + 有 ruby 数据）
        function wordRuby(word) {
            if (!furiganaEnabled || !word)
                return ""
            return word.ruby ? ("" + word.ruby) : ""
        }

        // 振假名字号：主字号的 0.42 倍，夹在 [8, 18] 内，避免过大压住主行
        readonly property int rubyPixelSize: Math.max(8, Math.min(18, Math.round(pixelSize * 0.42)))

        // 整行统一预留的注音高度：只要本行任意一词带注音就预留 rubyPixelSize，
        // 所有词一律加上同样的预留量。切勿改成「按词各自预留」——那样有注音的词
        // 会被推低、无注音的词留在原位，同一行主字出现高低错落（已踩过）。
        readonly property real lineReservedRuby: {
            if (!furiganaEnabled || !words)
                return 0
            for (var i = 0; i < words.length; ++i) {
                var w = words[i]
                if (w && w.ruby && ("" + w.ruby) !== "")
                    return rubyPixelSize
            }
            return 0
        }

        // 日语行：整行（含假名与汉字）走日语字体；其余行维持原文字体
        readonly property string effectiveFontFamily: {
            if (lineIsJapanese && japaneseFontFamily !== "")
                return japaneseFontFamily
            return fontFamily
        }
        readonly property int effectiveFontWeight: {
            if (lineIsJapanese && japaneseFontFamily !== "")
                return japaneseFontWeight
            return fontWeight
        }
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

        // MediaIsland / AMLL 长音辉光辅助：平滑贝塞尔波峰，避免突兀起停
        function sampleCubicBezier(parameter, control1, control2) {
            var inverse = 1 - parameter
            return (3 * inverse * inverse * parameter * control1)
                    + (3 * inverse * parameter * parameter * control2)
                    + (parameter * parameter * parameter)
        }

        function evaluateCubicBezier(x, cX1, cY1, cX2, cY2) {
            x = Math.max(0, Math.min(1, x))
            var lower = 0, upper = 1, parameter = x
            for (var i = 0; i < 20; i++) {
                var currentX = sampleCubicBezier(parameter, cX1, cX2)
                if (Math.abs(currentX - x) < 0.000001)
                    break
                if (currentX < x)
                    lower = parameter
                else
                    upper = parameter
                parameter = (lower + upper) / 2
            }
            return sampleCubicBezier(parameter, cY1, cY2)
        }

        function emphasisWaveResponse(progress) {
            progress = Math.max(0, Math.min(1, progress))
            if (progress <= 0 || progress >= 1)
                return 0
            return progress < 0.5
                   ? evaluateCubicBezier(progress / 0.5, 0.2, 0.4, 0.58, 1)
                   : 1 - evaluateCubicBezier((progress - 0.5) / 0.5, 0.3, 0, 0.58, 1)
        }

        function emphasisBlur(durationMs, isLastWord) {
            var blur = Math.max(1000, durationMs) / 3000
            blur = blur > 1 ? Math.sqrt(blur) : Math.pow(blur, 3)
            blur *= 0.5
            if (isLastWord)
                blur *= 1.5
            return Math.min(0.8, blur)
        }

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
                    required property int index
                    // 注音预留：整行统一（见 sweep.lineReservedRuby），保证同行的词
                    // 主字共底、不出现高低错落；无注音的行该值为 0，行高与主字号一致
                    readonly property real rubyHeight: sweep.lineReservedRuby
                    implicitWidth: baseText.width
                    implicitHeight: rubyHeight + baseText.height

                    // ---- 换行逐词入场（「炫酷 / 灵动 / 大幅度」的核心） ----
                    // 每个词自带 delay 错峰入场，位移取行高的 34%，缩放 1.32 → 1
                    // 走过冲回弹；两者都只在换行后的 760ms 内变化，随后恒为终态，
                    // 不影响卡拉OK 填充与跑马灯。
                    // 位移必须走 transform，不能写 `y:` —— delegate 是 Row 的子项，
                    // Row 的布局每次都会把 y 重设回 0，直接写 y 属性会被无声吃掉。
                    readonly property real enterProgress: root.wordEnterProgress(
                        index, index * root.wordStaggerMs, 460)
                    // 越靠后的词错峰越晚，用同一 Easing.OutBack 做一次速度归零的落地，
                    // 否则「迟到的词」看起来只是淡入，没有冲进来的感觉
                    readonly property real enterEased: root.easeOutBack(enterProgress)
                    // 位移幅度取字号比例而非 baseText.height：后者在首帧仍是 NaN
                    readonly property real enterTranslateY: (1 - enterEased) * sweep.pixelSize * 0.95
                    readonly property real enterScale: 1 + (1 - enterEased) * 0.32

                    transformOrigin: Item.Bottom
                    scale: enterScale
                    transform: Translate { y: wordItem.enterTranslateY }

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

                    // 长音辉光：仅逐字且时长 >1000ms；行级永不启用
                    readonly property real wordDurationMs: {
                        var w = wordItem.modelData
                        return w ? Math.max(0, w.endMs - w.startMs) : 0
                    }
                    readonly property bool longNoteEligible: sweep.wordTiming && wordDurationMs > 1000
                    readonly property bool isLastWord: {
                        return sweep.words && wordItem.index === sweep.words.length - 1
                    }
                    readonly property real glowBlur: {
                        if (!longNoteEligible)
                            return 0
                        return sweep.emphasisBlur(wordDurationMs, isLastWord)
                    }
                    readonly property real glowResponse: {
                        if (!longNoteEligible)
                            return 0
                        var w = wordItem.modelData
                        var pos = sweep.positionMs
                        if (pos <= w.startMs || pos >= w.endMs)
                            return 0
                        var progress = (pos - w.startMs) / Math.max(1, w.endMs - w.startMs)
                        return sweep.emphasisWaveResponse(progress)
                    }
                    readonly property real glowLevel: Math.max(0, Math.min(1, glowBlur * glowResponse))
                    readonly property bool glowActive: longNoteEligible && glowLevel > 0.02
                    readonly property real glowRadiusPx: {
                        if (glowBlur <= 0)
                            return 0
                        var em = Math.min(0.3, glowBlur * 0.3)
                        return Math.min(12, sweep.pixelSize * em)
                    }
                    readonly property real glowOpacity: Math.max(0, Math.min(1, glowLevel * 1.7))

                    // 长音辉光层：MediaIsland 回退同款环向采样，画在填充之下，
                    // 融入卡拉OK 而非独立叠层；仅逐字长音激活
                    Item {
                        id: glowLayer
                        anchors.fill: parent
                        visible: wordItem.glowActive
                        opacity: wordItem.glowOpacity
                        z: -1
                        Behavior on opacity {
                            NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
                        }

                        Repeater {
                            model: wordItem.glowActive ? 8 : 0
                            delegate: Text {
                                required property int index
                                readonly property real angle: Math.PI * 2 * index / 8
                                x: Math.cos(angle) * Math.max(1, wordItem.glowRadiusPx)
                                y: Math.sin(angle) * Math.max(1, wordItem.glowRadiusPx)
                                text: wordItem.modelData.text
                                color: sweep.fillColor
                                opacity: 0.55 / 8
                                font.family: sweep.effectiveFontFamily
                                font.pixelSize: sweep.pixelSize
                                font.weight: sweep.effectiveFontWeight
                            }
                        }

                        // 中心柔光：略抬不透明度，形成连续 bloom
                        Text {
                            text: wordItem.modelData.text
                            color: sweep.fillColor
                            opacity: 0.35
                            font.family: sweep.effectiveFontFamily
                            font.pixelSize: sweep.pixelSize
                            font.weight: sweep.effectiveFontWeight
                        }
                    }

                    // 振假名（ruby）：汉字上方小字，水平居中对齐该词；
                    // 与主字同色同填充进度，随卡拉OK 一起点亮，避免假名滞后/超前。
                    // 锚在整行统一的预留带底部，因此同行所有注音同一基线。
                    Text {
                        id: rubyText
                        objectName: "rubyText"
                        visible: text !== ""
                        anchors.horizontalCenter: baseText.horizontalCenter
                        anchors.bottom: baseText.top
                        text: sweep.wordRuby(wordItem.modelData)
                        color: sweep.wordTiming && wordItem.fillRatio < 1.0
                               ? sweep.baseColor : sweep.fillColor
                        font.family: sweep.effectiveFontFamily
                        font.pixelSize: sweep.rubyPixelSize
                        font.weight: sweep.effectiveFontWeight
                    }

                    Text {
                        id: baseText
                        anchors.top: parent.top
                        anchors.topMargin: wordItem.rubyHeight
                        text: wordItem.modelData.text
                        // 行级：底层也用满色，避免看起来像卡在唱完态的卡拉OK
                        color: sweep.wordTiming ? sweep.baseColor : sweep.fillColor
                        font.family: sweep.effectiveFontFamily
                        font.pixelSize: sweep.pixelSize
                        font.weight: sweep.effectiveFontWeight
                    }

                    // 卡拉OK顶层裁切：仅逐字模式启用
                    Item {
                        visible: sweep.wordTiming
                        anchors.left: parent.left
                        anchors.top: baseText.top
                        anchors.bottom: baseText.bottom
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
                            font.family: sweep.effectiveFontFamily
                            font.pixelSize: sweep.pixelSize
                            font.weight: sweep.effectiveFontWeight
                        }
                    }
                }
            }
        }
    }

    // 间奏呼吸点：三个点共享同一条基线与缩放，只靠透明度依次点亮，
    // 因此不会出现逐点位移的跳动感。动画数学与 MediaIsland 的
    // InterludeDotsPresenter 对齐（时间单位 ms）：
    // - 呼吸周期按 1.5s 向上取整后均分整段间奏，最后一个完整周期恰好落在间奏内
    // - 入场 2s 指数缓出 + 前 500ms 不可见、再 500ms 淡入，避免刚进入间奏就闪现
    // - 收尾 750ms 缩小、最后 375ms 淡出，交接给下一句的暗色预览
    // 时间来源是后端 100ms 节拍，所以每个动画输出都挂 90ms 缓动，
    // 与卡拉OK填充 / 跑马灯同一套节拍约定
    component InterludeDots: Item {
        id: dots

        property int startMs: 0
        property int endMs: 0
        property int positionMs: 0
        property color color: "#FFFFFF"
        property int pixelSize: 28

        readonly property real durationMs: Math.max(0, endMs - startMs)
        readonly property real elapsedMs: Math.max(0, Math.min(durationMs, positionMs - startMs))
        readonly property real remainingMs: durationMs - elapsedMs
        readonly property real breatheMs: durationMs / Math.max(1, Math.ceil(durationMs / 1500))
        // 点半径按字号缩放并夹在 [2, 5.5]，与参考实现同量级
        readonly property real dotRadius: Math.max(2, Math.min(5.5, pixelSize * 0.22))
        readonly property real dotSpacing: dotRadius * 3.3
        readonly property real dotsDuration: Math.max(1, durationMs - 750)

        readonly property real waveScale: {
            if (durationMs <= 0)
                return 0
            var value = 1 + Math.sin(1.5 * Math.PI - (elapsedMs / breatheMs) * 2) / 20
            if (elapsedMs < 2000)
                value *= easeOutExpo(elapsedMs / 2000)
            if (remainingMs < 750)
                value *= 1 - easeInOutBack((750 - remainingMs) / 750 / 2)
            return Math.max(0, value) * 0.82
        }

        readonly property real globalOpacity: {
            if (durationMs <= 0 || elapsedMs <= 0)
                return 0
            var value = 1
            if (elapsedMs < 500)
                value = 0
            else if (elapsedMs < 1000)
                value = (elapsedMs - 500) / 500
            if (remainingMs < 375)
                value *= Math.max(0, Math.min(1, remainingMs / 375))
            return Math.max(0, Math.min(1, value))
        }

        // 三个点按可见期的 1/3 时差依次淡入，最低透明度 0.25，后两点不会长时间全灭
        function dotOpacity(index) {
            var raw = (elapsedMs - dotsDuration / 3 * index) * 3 / dotsDuration * 0.75
            var staggered = Math.max(0.25, Math.min(1, raw))
            return Math.max(0, Math.min(1, staggered * globalOpacity))
        }

        function easeOutExpo(progress) {
            if (progress <= 0)
                return 0
            if (progress >= 1)
                return 1
            return 1 - Math.pow(2, -10 * progress)
        }

        function easeInOutBack(progress) {
            var p = Math.max(0, Math.min(1, progress))
            var factor = 1.70158 * 1.525
            return p < 0.5
                    ? Math.pow(2 * p, 2) * ((factor + 1) * 2 * p - factor) / 2
                    : (Math.pow(2 * p - 2, 2) * ((factor + 1) * (p * 2 - 2) + factor) + 2) / 2
        }

        // 预留放大后的点与点距，避免呼吸缩放在边缘被 RowLayout 裁掉
        implicitWidth: (dotRadius * 2 + dotSpacing * 2) * 1.1
        implicitHeight: Math.max(pixelSize * 1.2, dotRadius * 2 * 1.1)

        Item {
            id: dotStage
            anchors.centerIn: parent
            width: dots.implicitWidth
            height: dots.implicitHeight
            scale: dots.waveScale
            Behavior on scale {
                NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
            }

            Repeater {
                model: 3

                delegate: Rectangle {
                    required property int index
                    width: dots.dotRadius * 2
                    height: width
                    radius: width / 2
                    color: dots.color
                    opacity: dots.dotOpacity(index)
                    x: dots.implicitWidth / 2 + (index - 1) * dots.dotSpacing - width / 2
                    y: (dots.implicitHeight - height) / 2

                    Behavior on opacity {
                        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
                    }
                }
            }
        }
    }
}
