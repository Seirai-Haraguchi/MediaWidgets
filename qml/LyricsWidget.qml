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

    // 有可用歌词 / 正在搜索 / 编辑模式 → 显示；nomatch/error 才隐藏。
    // loading 不算「无歌词」，防止搜索过程中组件闪烁消失。
    // 判据读 observedState 而不是 backend.state：换歌那一瞬的 idle 是切曲的中间态，
    // 由 observeState 与 songTransitionHold 一起并入（详见该函数注释）——
    // 否则整组件会在换歌瞬间先播一次退场淡出，把横扫动画整个盖掉。
    // hold 必须再与 hasMedia 相与：播放器停止时后端同样走 ready → idle，
    // 只认 hold 会让组件卡在「未在播放」上不消失（正常该隐藏）。
    readonly property bool lyricsUsable: observedState === "ready"
    readonly property bool lyricsLoading: observedState === "loading"
    readonly property bool shouldShow: lyricsUsable || lyricsLoading || editMode
                                       || (songTransitionHold && hasMedia)

    // 当前是否处于间奏：主行换成呼吸点（后端只在「有文档且落在长空档内」时为真）
    readonly property bool interludeActive: backend !== null
                                            && observedState === "ready" && backend.interlude

    // 主行是否走「状态文案」而不是歌词。
    // 换歌的「送出」窗口内刻意不走 —— 那一瞬 observedState 会落到 idle / loading，
    // 若照它显示「正在获取歌词…」，刚起步的送出动画会被一行状态文案当场顶掉，
    // 等于看不到歌词滑出（这正是「切歌动画看不见」的另一半原因）。
    // 送出播完（songSweepingOut 落下）才把状态文案顶上来，覆盖住等新歌词的空档。
    readonly property bool statusTextActive: !backend
                                             || (observedState !== "ready"
                                                 && !songSweepingOut)

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
    // 换行 / 换歌动画总开关：关闭后回落到轻量淡入（低配机器或不喜欢大幅动效）
    readonly property bool lyricAnimationsEnabled: pluginConfig
                                                   ? pluginConfig.lyric_animation_enabled !== false
                                                   : true

    // 卡拉OK双色：已唱满色、未唱半透明；主文字色不用专辑主色，保证任何封面下都可读
    readonly property color sungColor: Rin.Theme.isDark() ? "#FFFFFF" : "#1B1B1B"
    readonly property color unsungColor: Rin.Theme.isDark() ? Qt.alpha("#FFFFFF", 0.40) : Qt.alpha("#000000", 0.40)

    // 顶部歌名：框架只暴露 `text` 别名（property alias text: subtitleLabel.text），
    // 拿不到那个 Text 实例，也就无法给它挂位移 / 淡入淡出。
    // 所以框架标题留空，真歌名改到 `subtitle` 槽位自绘 —— 与 CW2 内置的
    // dynamicNotification.qml 完全同款写法（subtitle: Subtitle { ... }），
    // 直接复用框架 Subtitle 组件，字号 / 字重 / 主题覆写都自动跟随。
    //
    // 为什么留空串也不会让 header 行消失：BaseWidget 的判据是
    //     visible: (subtitle.length > 1 || actions.length > 1 || text.length > 0) && !miniMode
    // 往 subtitle 槽位加一项后 subtitle.length 变成 2，前一个分支已成立。
    // 空串的 subtitleLabel 宽度为 0，不占横向空间、行高也与原来一致。
    text: ""

    // 自绘歌名：位移 / 不透明度直接挂在 Subtitle 上。
    // 切勿再套一层 Item 外壳 —— subtitle 是 subtitleArea.children 的**列表别名**，
    // 外壳会让槽位里多出一层容器，布局与对齐都会跟着漂（内置组件都是直挂）。
    subtitle: Subtitle {
        id: headerLabel
        objectName: "headerLabel"
        text: root.backend && root.hasMedia ? root.media.title : qsTr("Lyrics")
        // 框架 Subtitle 自带 opacity: 0.6，这里在它之上叠换歌的淡出淡入
        opacity: 0.6 * root.songOpacity
        // 换歌横扫：与下方歌词块同一套位移，歌名与歌词一起非线性平移
        transform: Translate { x: root.songSlideX }
    }

    // 换行时轻微淡入，突出逐字扫描主体。
    // 目标是 root 上的独立属性而不是 sweepRow.opacity —— 后者现在由
    // lyricOpacity 统一合成，直接对其做动画会与绑定打架。
    property real linePopOpacity: 1
    NumberAnimation {
        id: linePop
        target: root
        property: "linePopOpacity"
        from: 0.35
        to: 1
        duration: 260
        easing.type: Easing.OutQuad
    }

    // ---- 歌词块动画 ----
    // 设计取向「炫酷 / 灵动 / 大幅度」。换行与换歌是两套方向不同的运动：
    //   换行：旧行整体上抬淡出 → 换词 → 新行自下方错峰落位（纵向）
    //   换歌：旧内容整体右滑淡出 → 换曲 → 新内容自左侧非线性映入（横向，Material 强调曲线）
    // 两者都由「归一化进度」驱动，静息值即终态，对常规布局零影响。
    //
    // 为什么渲染用词表要自己持有一份（shownWords）：后端在 emit lineChanged
    // **之前**就已经把 words 换成新行了，通知到达时旧文本已不存在 ——
    // 对「已经消失的内容」无法补动画。所以「送出旧行」必须在换词之前完成，
    // 换词时机由本组件掌握（见 commitPendingLine）。

    // 当前实际渲染的行快照（不直接绑 backend.words）
    property var shownWords: []
    property bool shownWordTiming: false
    property string shownSubLine: ""
    property bool shownSubIsTranslation: false
    property bool shownLineIsJapanese: false

    function applyLine(words, wordTiming, subLine, subIsTranslation, japanese) {
        shownWords = words
        shownWordTiming = wordTiming
        shownSubLine = subLine
        shownSubIsTranslation = subIsTranslation
        shownLineIsJapanese = japanese
    }

    function clamp01(value) {
        return Math.max(0, Math.min(1, value))
    }

    // 速度归零的过冲缓出：用于逐词落地的回弹
    function easeOutBack(progress) {
        var p = clamp01(progress)
        var factor = 1.70158
        var shifted = p - 1
        return 1 + (factor + 1) * Math.pow(shifted, 3)
               + factor * Math.pow(shifted, 2)
    }

    function easeInCubic(progress) {
        var p = clamp01(progress)
        return p * p * p
    }

    function easeOutCubic(progress) {
        var p = clamp01(progress)
        var inverse = 1 - p
        return 1 - inverse * inverse * inverse
    }

    // Material 3「强调减速」cubic-bezier(0.05, 0.7, 0.1, 1)：
    // 起步极快、长尾缓收 —— 这就是「非线性平移」的观感来源（类似 Material You）。
    // 二分法解 x→t 再取 y，避免闭式解在端点附近不稳定。
    function bezierAxis(parameter, control1, control2) {
        var inverse = 1 - parameter
        return 3 * inverse * inverse * parameter * control1
               + 3 * inverse * parameter * parameter * control2
               + parameter * parameter * parameter
    }

    function emphasizedDecelerate(progress) {
        var x = clamp01(progress)
        var lower = 0, upper = 1, parameter = x
        for (var i = 0; i < 24; ++i) {
            var currentX = bezierAxis(parameter, 0.05, 0.1)
            if (Math.abs(currentX - x) < 0.000001)
                break
            if (currentX < x)
                lower = parameter
            else
                upper = parameter
            parameter = (lower + upper) / 2
        }
        return bezierAxis(parameter, 0.7, 1)
    }

    // ---- 换行：一条 0 → 1 的归一化进度 ----
    // 前 lineSwapAtMs 是「送出」阶段（画面里仍是旧行），之后是「映入」阶段（新行）。
    property real linePulse: 1
    property var pendingLine: null
    readonly property int lineSwapAtMs: 200
    readonly property int lineWordSpanMs: 400

    // 本次换行的时长参数在**开始时一次性定死**，不随 shownWords 现算：
    // 切换点一到 shownWords 就换成新行，若时长跟着新行词数重算，
    // lineElapsedMs = linePulse × 时长 会在动画中途跳一下（进度不连续），
    // 入场会「抽搐」一次。定死之后 linePulseAnim.duration 全程不变。
    property int activeWordStaggerMs: 26
    property int activeEnterWindowMs: 400
    property int activePulseDuration: 1

    // 逐词错峰间距：词多则压缩，保证最后一个词也落在映入窗口内
    function wordStaggerFor(wordCount) {
        var n = Math.max(1, wordCount)
        return Math.max(12, Math.min(52, Math.round(260 / n)))
    }

    readonly property real lineElapsedMs: linePulse * activePulseDuration
    readonly property bool lineSwapDone: lyricAnimationsEnabled && lineElapsedMs >= lineSwapAtMs

    // 送出阶段的线性进度（真实时间 ↔ 进度线性对应）
    readonly property real lineExitLinear: clamp01(lineElapsedMs / lineSwapAtMs)
    // 位移用前段快、后段缓的 easeOutCubic：旧行一上来就明显抬起来。
    // 若用 easeInCubic（前段几乎不动、后段猛冲），位移会被同时进行的淡出盖掉，
    // 观感上等于「没有滑出」—— 实测 45% 处才抬起 9%，肉眼根本看不见。
    readonly property real lineExitProgress: {
        if (!lyricAnimationsEnabled)
            return 0
        return easeOutCubic(lineExitLinear)
    }
    readonly property real lineEnterProgress: {
        if (!lyricAnimationsEnabled)
            return 1
        var elapsed = lineElapsedMs - lineSwapAtMs
        if (elapsed <= 0)
            return 0
        return emphasizedDecelerate(elapsed / Math.max(1, activeEnterWindowMs))
    }

    // 逐词进度只在「映入」阶段推进；送出阶段恒为终值 —— 词组保持原位，
    // 由整行位移负责把旧行抬走（否则旧行会先被逐词偏移打散，不像一整行滑出）。
    function wordEnterProgress(index, delay, span) {
        if (!lyricAnimationsEnabled || linePulse >= 1)
            return 1
        if (lineElapsedMs < lineSwapAtMs)
            return 1
        var elapsed = lineElapsedMs - lineSwapAtMs - delay
        if (elapsed <= 0)
            return 0
        return clamp01(elapsed / span)
    }

    // 进度驱动器：linePulse 从 0 线性走到 1（真实时间 ↔ 进度线性对应），
    // 缓动在各阶段内部各自施加，便于精确分配「送出 / 映入」的时长。
    // 注意 id 绝不能叫 linePulse —— QML 里 id 优先级高于属性名，同名会让
    // 函数体里的 linePulse 解析成动画对象（算术得 NaN，且不报任何错）。
    NumberAnimation {
        id: linePulseAnim
        target: root
        property: "linePulse"
        from: 0
        to: 1
        duration: root.activePulseDuration
        easing.type: Easing.Linear
    }

    // 到切换点就换词（pendingLine 在 beginLineChange 里写入）。
    // 三个条件缺一不可：
    //   1. pendingLine 已挂 —— 本次换行确实有行要换
    //   2. 进度驱动器**正在跑** —— 否则这次 lineElapsedMs 变化只是归零/复位副作用
    //   3. 已越过切换点
    // 只判派生的 lineSwapDone 是不够的：QML 派生属性是惰性求值的，归零那一瞬
    // 处理器可能赶在它重算之前跑，读到的是上一轮的「已过切换点」真值 ——
    // 实测会出现 elapsed 已经读到 0、却当场把新词提交上去，旧行根本没机会送出。
    // 所以这里直接读 lineElapsedMs（读取会强制重算，拿到的是当前值）。
    onLineElapsedMsChanged: {
        if (!pendingLine || !linePulseAnim.running)
            return
        if (lineElapsedMs >= lineSwapAtMs)
            commitPendingLine()
    }

    function commitPendingLine() {
        if (!pendingLine)
            return
        var line = pendingLine
        pendingLine = null
        applyLine(line.words, line.wordTiming, line.subLine,
                  line.subIsTranslation, line.japanese)
        // 换行总是从行首显示：瞬时归零滚动，避免沿用上一行偏移
        sweepRow.prepareLineChange()
    }

    // ---- 换歌：送出 / 映入两段独立进度 ----
    // 不能用单一进度：新曲目的歌词何时到达是异步的（可能几百毫秒后才 ready），
    // 「映入」只能等拿到首行再启动。
    property real songOutProgress: 0
    property real songInProgress: 1
    // 本次换歌还没有渲染过任何一行（决定新曲目首行走横向映入还是纵向换行）
    property bool songFirstLinePending: false
    property bool deferredSongLine: false

    // 整块内容的横向位移：旧内容向右送出（0 → +span），新内容自左侧映入（−span → 0）
    readonly property real songSweepSpan: Math.max(56, contentRow.width * 0.34)
    readonly property real songSlideX: easeInCubic(songOutProgress) * songSweepSpan
                                       - (1 - emphasizedDecelerate(songInProgress)) * songSweepSpan
    // 整块内容的淡出淡入；静息值 1
    readonly property real songOpacity: clamp01((1 - songOutProgress) * songInProgress)

    // 换歌过渡进行中（送出阶段 / 等首行 / 映入阶段）。
    // 刻意用显式标志，不由 songOutProgress / songInProgress 推导：beginSongSweep() 里
    // songOutAnim.start() 只是把动画排上队，进度要等下一帧才动，而后端的 _clear_line()
    // 紧跟着**同步**发来一条空词表的 lineChanged —— 那一刻推导出来的「未在过渡」会让
    // 这个空行被当成真换行提交，刚起步的送出动画当场被打断，等于又看不到滑出。
    property bool songEpisodeActive: false
    // 送出动画是否正在播：只有这段窗口里才让旧行留在画面上滑出去，
    // 之后（等新歌词的空档）把状态文案顶上来，卡片不至于白着干等。
    readonly property bool songSweepingOut: songOutAnim.running

    NumberAnimation {
        id: songOutAnim
        target: root
        property: "songOutProgress"
        from: 0
        to: 1
        duration: root.lyricAnimationsEnabled ? 220 : 1
        easing.type: Easing.Linear
        onFinished: {
            // 新行在送出动画还没播完时就到了：等这里收尾再映入，别把送出截成半截
            if (root.deferredSongLine) {
                root.deferredSongLine = false
                root.startSongEnter()
                return
            }
            if (root.observedState === "ready")
                root.settleSongEpisode()
        }
    }

    // 兜底计时器：ready 之后仍拿不到首行时强制结束过渡。
    // 不设它的话，songOpacity 会停在 (1-1)×1 = 0，整块内容（含间奏三点呼吸点）
    // 一直不可见 —— 「新曲目一上来就是长间奏」时后端不会发 lineChanged，必然踩到。
    Timer {
        id: songFirstLineWatchdog
        interval: 450
        repeat: false
        onTriggered: {
            if (!root.songFirstLinePending)
                return
            if (root.backend)
                root.applyLine(root.backend.words, root.backend.wordTiming,
                               root.backend.subLine, root.backend.subIsTranslation,
                               root.backend.lineIsJapanese)
            root.resetSongEpisode()
        }
    }

    // 送出播完 / ready 到来后调用：能收尾就收尾，收不了就挂看门狗
    function settleSongEpisode() {
        if (!songFirstLinePending || songOutAnim.running)
            return
        // 后端已持有新行 → 立刻横向映入（首行跟着整块一起从左侧进来）
        if (backend && backend.words && backend.words.length > 0) {
            startSongEnter()
            return
        }
        if (!songFirstLineWatchdog.running)
            songFirstLineWatchdog.restart()
    }

    NumberAnimation {
        id: songInAnim
        target: root
        property: "songInProgress"
        from: 0
        to: 1
        duration: root.lyricAnimationsEnabled ? 560 : 1
        easing.type: Easing.Linear
        onFinished: root.songEpisodeActive = false
    }

    function resetSongEpisode() {
        songFirstLineWatchdog.stop()
        songOutAnim.stop()
        songInAnim.stop()
        songOutProgress = 0
        songInProgress = 1
        songFirstLinePending = false
        deferredSongLine = false
        songEpisodeActive = false
    }

    function beginSongSweep() {
        if (!lyricAnimationsEnabled) {
            resetSongEpisode()
            return
        }
        songFirstLineWatchdog.stop()
        songOutAnim.stop()
        songInAnim.stop()
        songOutProgress = 0
        songInProgress = 1
        songFirstLinePending = true
        deferredSongLine = false
        // 必须在 start() 之前立起来：stop()/start() 之间会同步跑过后端的 _clear_line()
        songEpisodeActive = true
        songOutAnim.start()
    }

    // 新曲目首行：走横向映入
    function startSongEnter() {
        if (!backend)
            return
        songFirstLineWatchdog.stop()
        applyLine(backend.words, backend.wordTiming, backend.subLine,
                  backend.subIsTranslation, backend.lineIsJapanese)
        sweepRow.prepareLineChange()
        songFirstLinePending = false
        // 先归零送出进度：此刻 songInProgress 为 0，整块不可见，位置突跳看不出来
        songOutProgress = 0
        songInProgress = 0
        songInAnim.restart()
    }

    // ---- 歌词块的统一位移与不透明度 ----
    // 纵向：送出阶段整体上抬，映入阶段自下方落位
    readonly property real lineLiftPx: Math.max(12, sweepRow.pixelSize * 0.6)
    readonly property real lyricSlideY: {
        if (!lyricAnimationsEnabled || linePulse >= 1)
            return 0
        if (lineElapsedMs < lineSwapAtMs)
            return -lineExitProgress * lineLiftPx
        return (1 - easeOutCubic(lineEnterProgress)) * lineLiftPx
    }
    readonly property real lineOpacity: {
        if (!lyricAnimationsEnabled || linePulse >= 1)
            return 1
        if (lineElapsedMs < lineSwapAtMs)
            // 淡出故意走后段加速（easeInCubic）：位移先走、透明度后掉。
            // 两者同步的话内容还没抬起来就淡没了，等于白做位移。
            return 1 - easeInCubic(lineExitLinear)
        return lineEnterProgress
    }
    // 换歌（横向 + 整块）× 换行（纵向 + 淡出）× 关动画时的轻量淡入
    readonly property real lyricSlideX: songSlideX
    readonly property real lyricOpacity: songOpacity * lineOpacity * linePopOpacity

    onLyricAnimationsEnabledChanged: {
        // 关掉时把动画留下的中间态立刻归位，否则会停在歪斜/半透明上
        linePulseAnim.stop()
        resetSongEpisode()
        linePulse = 1
        activePulseDuration = 1
        pendingLine = null
        if (!lyricAnimationsEnabled && backend) {
            // 可能还挂着未提交的词表切换，立刻落位
            applyLine(backend.words, backend.wordTiming, backend.subLine,
                      backend.subIsTranslation, backend.lineIsJapanese)
        }
    }

    // 换行扫掠高光：一条窄光带沿行内从左到右扫过，只在新行映入阶段出现。
    // 位置必须用 mapToItem 换算到 root 坐标 —— 直接拿 sweepRow.x/y 当 root 坐标
    // 会把光带画到组件顶部去（sweepRow 的坐标相对 contentRow，而 contentRow 又被
    // contentArea 的左内边距与 header 行高整体下移）。光带宽度收在行宽以内，
    // 不再扫到组件外面。
    readonly property point sweepOriginPoint: contentRow.mapToItem(root, sweepRow.x, sweepRow.y)
    readonly property real sweepBarWidth: Math.max(24, sweepRow.width * 0.28)

    Rectangle {
        id: lineSweepHighlight
        objectName: "lineSweepHighlight"
        parent: root
        // 只在映入阶段出现：光带扫过的正是「刚落位的新行」
        visible: root.lyricAnimationsEnabled && root.lineSwapDone
                 && root.linePulse < 1 && sweepRow.visible
        width: root.sweepBarWidth
        height: 2
        radius: 1
        color: root.sungColor
        opacity: visible ? 0.5 * Math.sin(Math.PI * root.clamp01(root.lineEnterProgress)) : 0
        x: root.sweepOriginPoint.x - root.sweepBarWidth
           + root.lineEnterProgress * (sweepRow.width + root.sweepBarWidth)
        // 压在主行文字下缘（穿过字身中段会被字形盖住、只剩缝里那点，几乎看不见）
        y: root.sweepOriginPoint.y + sweepRow.height - 3

        Behavior on opacity {
            NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
        }
    }

    // ---- 换行入口 ----
    function beginLineChange() {
        if (!backend)
            return
        var words = backend.words

        if (songEpisodeActive) {
            // 换歌过程中的 _clear_line()（words 为空）不是真换行，忽略即可 ——
            // 若在这里归位，刚起步的「送出」动画会被立刻打断、等于没有滑出。
            if (!words || words.length === 0)
                return
            if (songFirstLinePending) {
                if (songOutAnim.running) {
                    // 送出还没播完，等它收尾再映入
                    deferredSongLine = true
                    return
                }
                startSongEnter()
                return
            }
        }

        var line = { words: words, wordTiming: backend.wordTiming,
                     subLine: backend.subLine,
                     subIsTranslation: backend.subIsTranslation,
                     japanese: backend.lineIsJapanese }

        if (!lyricAnimationsEnabled) {
            linePulseAnim.stop()
            linePulse = 1
            activePulseDuration = 1
            activeEnterWindowMs = 1
            pendingLine = line
            commitPendingLine()
            linePop.restart()
            return
        }
        // 顺序不可颠倒，且「挂待换行」必须排在归零**之后**：
        // 归零会让 lineElapsedMs 从「已越过切换点」的大值跳回 0，而派生属性是惰性
        // 求值的 —— 变化处理器有可能赶在 lineSwapDone 重算之前跑、读到上一轮的真值，
        // 当场就把新词提交上去。此时 pendingLine 还是 null，这一步天然免疫。
        linePulseAnim.stop()
        linePulse = 0
        var count = (words && words.length) ? words.length : 1
        activeWordStaggerMs = wordStaggerFor(count)
        activeEnterWindowMs = lineWordSpanMs + activeWordStaggerMs * (count - 1)
        activePulseDuration = lineSwapAtMs + activeEnterWindowMs
        pendingLine = line
        linePulseAnim.start()
    }

    // ---- 后端状态观察 ----
    // 可见性判据不能直接读 backend.state：换歌时后端把 state 从 ready 瞬降到 idle
    // （同一次调用里紧接着转 loading），若照 idle 判 shouldShow=false，整组件会先播
    // 一次退场淡出，把横扫动画整个盖掉 —— 这正是「换歌动画看不见」的根因。
    // 所以把「状态」与「换歌过渡标志」放在同一个函数里一次性写入，
    // 保证 shouldShow 只按最终值求值一次，不会落在中间态上。
    property string observedState: ""
    property bool songTransitionHold: false

    function observeState(nextState) {
        // 判据用「离开了一个有内容的状态」而不是「刚才是否 ready」：
        // 首曲还在 loading 时用户就切歌，走的是 loading → idle，若只认 ready→idle，
        // 这一瞬 shouldShow 会掉到 false，整组件先淡出再淡入，闪一下。
        var hadContent = observedState !== "" && observedState !== "idle"
        if (nextState === "idle" && hadContent) {
            // 顺序不可颠倒：先立标志（此刻 observedState 仍是旧值，
            // shouldShow 依旧为真，这次求值不会引发退场），再写状态。
            songTransitionHold = true
            beginSongSweep()
        } else if (nextState === "ready" || nextState === "nomatch"
                   || nextState === "error") {
            songTransitionHold = false
            if (nextState === "ready")
                settleSongEpisode()
            else
                resetSongEpisode()
        }
        observedState = nextState
    }

    // backend 是创建后才注入的，注入那一刻可能已经是 ready/loading，
    // 必须主动同步一次，否则要等下一次 stateChanged 才有可见性。
    // 同时补一次行快照：后端可能早就发过 lineChanged（连接建立之前），
    // 快照式渲染不去主动取一次的话，得等到下一次换行才有内容。
    onBackendChanged: {
        observeState(backend ? backend.state : "")
        if (backend)
            applyLine(backend.words, backend.wordTiming, backend.subLine,
                      backend.subIsTranslation, backend.lineIsJapanese)
    }

    Connections {
        target: root.backend
        function onStateChanged() {
            root.observeState(root.backend ? root.backend.state : "")
        }
        function onLineChanged() {
            root.beginLineChange()
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

        // 换歌横扫（横向，Material 强调曲线）× 换行抬升（纵向）× 淡入淡出，
        // 静息时位移为 0、不透明度为 1，对常规布局零影响。
        // 不用 x / width / height —— 锚点会吃掉 x，而宽度受框架收窄逻辑约束，
        // 都不参与动画；transform 锚点管不到，是唯一可靠通道。
        opacity: root.lyricOpacity
        transform: Translate { x: root.lyricSlideX; y: root.lyricSlideY }

        // 当前行：状态文案 与 逐字扫描 二选一，同为 Title 标尺
        // 状态文案用框架 Title（CW2 内置组件的占位写法，如 Nothing right now）
        Title {
            id: statusText
            visible: root.statusTextActive
            text: {
                if (!backend)
                    return ""
                if (!root.hasMedia)
                    return qsTr("未在播放")
                switch (root.observedState) {
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
            // 渲染词表读**快照**而不是 backend.words：后端在 emit lineChanged 之前
            // 就已把 words 换成新行，直接绑后端的话旧行在通知到达时已经不存在，
            // 「滑出」根本没东西可动。快照由 applyLine / commitPendingLine 掌握时机。
            words: root.shownWords
            wordTiming: root.shownWordTiming
            positionMs: backend ? backend.positionMs : 0
            baseColor: root.unsungColor
            fillColor: root.sungColor
            pixelSize: root.titlePx
            fontFamily: root.originalFontFamily
            fontWeight: root.originalFontWeight
            lineIsJapanese: root.shownLineIsJapanese
            furiganaEnabled: root.furiganaEnabled
            japaneseFontFamily: root.japaneseFontFamily
            japaneseFontWeight: root.japaneseFontWeight

            // 整体呼吸缩放：整行一个值（取自算力最省的「全行入场均值」），
            // 不逐词算——逐词缩放会让同行各词大小不一，观感像渲染错误。
            // 换行后只做一次 1.05 → 1 的回落，随后恒为 1，不影响卡拉OK 扫描。
            // 注意：不能用 baseText.height（首帧还未布局，会得到 NaN 并把整个
            // delegate 的 scale 污染成 NaN，入场动画直接消失）。
            readonly property real lineEnterScale: {
                if (!root.lyricAnimationsEnabled || root.linePulse >= 1)
                    return 1
                // 起步略过冲再回落，给出「弹一下」的灵动感；
                // 送出阶段 lineEnterProgress 恒为 0，缩放保持 1 不起伏
                return 1 + 0.06 * Math.sin(Math.PI * Math.min(1, root.lineEnterProgress * 1.15))
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
            text: root.shownSubLine
            maximumWidth: 200
            speed: 100
            opacity: root.shownSubIsTranslation ? 0.62 : 0.38
            font.family: root.shownSubIsTranslation
                         ? root.translationFontFamily : root.originalFontFamily
            font.weight: root.shownSubIsTranslation
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

        // 入场位移需要纵向余量。裁切本身只为「按宽度裁掉跑马灯溢出」，但逐词入场是
        // 从下方近一个字高处冲上来、注音与回弹缩放还会向上溢 —— 若裁切区恰好等于
        // 行高，新行整个入场过程都发生在裁切区之外，只剩落位前最后一小段可见，
        // 观感就是「没有入场动画」。所以把裁切下移到内层视口，上下各留一段余量；
        // 横向裁切行为与原来完全一致（视口宽度 = 组件宽度）。
        // 余量取一个字号：正好覆盖逐词入场的 0.95em 位移。余量本身是空白区域，
        // 只有当词真的偏移到那里（那一刻不透明度≈0）才会有内容，不会画出界。
        readonly property real verticalClipMargin: Math.max(8, Math.ceil(pixelSize * 1.05))

        Item {
            id: sweepViewport
            y: -sweep.verticalClipMargin
            width: sweep.width
            height: sweep.height + sweep.verticalClipMargin * 2
            clip: true
        }

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
            // 挂进上方那个带纵向余量的裁切视口。用 parent 而不是把整段 delegate
            // 再缩进一层，语义等价（Row 成为视口的子项）但 diff 最小。
            parent: sweepViewport
            spacing: 0
            x: sweep.displayedScrollX
            // 视口整体上移了 margin，这里补偿回来，词行在组件里的位置不变
            y: sweep.verticalClipMargin

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
                        index, index * root.activeWordStaggerMs, 460)
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
