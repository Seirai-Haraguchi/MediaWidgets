import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI

// Media Widgets 插件同名设置页（CW2 设置 → 插件 → Media Widgets）
// - main.py 在 on_load 时经 api.ui.register_settings_page 注册本页；
// - 在播信息来自 main.py 注册进 PluginBackendBridge 的媒体后端（与桌面小组件同源）；
// - 开关经 Configs.setPlugin 写入 configs.plugins.configs[pid]，
//   Python 侧（lyrics_pusher）从同一路径实时读取，改动立即生效。
FluentPage {
    id: root
    horizontalPadding: 0
    wrapperWidth: width - 42 * 2
    spacing: 4
    title: qsTr("Media Widgets")

    // 插件 id 固定：RinUI 导航项点击不透传 properties，页面自持 id
    property string pluginId: "com.seiraiharaguchi.mediawidgets"
    property var backend: typeof PluginBackendBridge !== "undefined"
                          ? PluginBackendBridge.get_backend(pluginId) : null
    property bool hasMedia: root.backend && root.backend.title !== ""

    function config(key, fallback) {
        var cfg = Configs.data.plugins && Configs.data.plugins.configs
        if (!cfg || !cfg[root.pluginId]) return fallback
        var v = cfg[root.pluginId][key]
        return v === undefined ? fallback : v
    }

    // ---------- 正在播放 ----------

    Text {
        Layout.fillWidth: true
        Layout.topMargin: 8
        typography: Typography.BodyStrong
        text: qsTr("正在播放")
    }

    Frame {
        id: nowPlayingCard
        Layout.fillWidth: true
        Layout.topMargin: 4
        hoverable: false
        leftPadding: 16
        rightPadding: 16
        topPadding: 16
        bottomPadding: 16
        // 卡内有两个子项（内容列 + 右上角覆盖行），Pane 无法自动推算隐式大小，
        // 按官方文档显式绑定内容高度，否则 Frame 塌缩成一条、内容被 clip 裁掉
        contentHeight: mediaColumn.implicitHeight

        ColumnLayout {
            id: mediaColumn
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 16

                // 封面：后端输出的 PNG 已烘焙圆角（64px 显示 ≈ 14px 半径）
                Item {
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 64

                    Rectangle {
                        anchors.fill: parent
                        radius: 14
                        color: Qt.alpha(root.backend ? root.backend.accentColor : "#9AA0A6", 0.18)
                        visible: artImage.status !== Image.Ready
                    }

                    Image {
                        id: artImage
                        anchors.fill: parent
                        source: root.hasMedia ? root.backend.art : ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        visible: status === Image.Ready
                    }

                    Icon {
                        anchors.centerIn: parent
                        name: "ic_fluent_music_note_2_20_regular"
                        size: 26
                        color: Colors.proxy.textSecondaryColor
                        visible: artImage.status !== Image.Ready
                    }

                    // 播放源图标角标预览：与桌面媒体组件同款样式
                    Rectangle {
                        width: 18
                        height: 18
                        radius: 9
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.rightMargin: -3
                        anchors.bottomMargin: -3
                        visible: root.config("show_source_badge", false)
                                 && root.hasMedia && root.backend.sourceIcon !== ""
                        color: Theme.isDark() ? "#2B2B2B" : "#FFFFFF"
                        border.width: 1
                        border.color: Theme.isDark() ? Qt.alpha("#FFFFFF", 0.18) : Qt.alpha("#000000", 0.12)

                        Image {
                            anchors.fill: parent
                            anchors.margins: 4
                            source: root.hasMedia ? root.backend.sourceIcon : ""
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            smooth: true
                            mipmap: true
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: root.hasMedia ? root.backend.title : qsTr("未在播放")
                        typography: Typography.Subtitle
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.hasMedia && root.backend.artist
                              ? root.backend.artist : qsTr("当前没有正在播放的媒体")
                        typography: Typography.Body
                        color: Colors.proxy.textSecondaryColor
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                    }
                }

                Icon {
                    name: root.backend && root.backend.isPlaying
                          ? "ic_fluent_pause_20_regular" : "ic_fluent_play_20_regular"
                    size: 20
                    color: Colors.proxy.textSecondaryColor
                    visible: root.hasMedia
                }
            }

            // 进度条：专辑主色填充，平滑动画
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 4
                radius: 2
                color: Colors.proxy.controlAltSecondaryColor

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: parent.width * (root.backend ? root.backend.progress : 0)
                    radius: 2
                    color: root.backend ? root.backend.accentColor : "#9AA0A6"
                    Behavior on width {
                        NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: root.backend ? root.backend.positionText : ""
                    typography: Typography.Caption
                    color: Colors.proxy.textSecondaryColor
                    visible: root.hasMedia
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: root.backend ? root.backend.durationText : ""
                    typography: Typography.Caption
                    color: Colors.proxy.textSecondaryColor
                    visible: root.hasMedia
                }
            }
        }

        // 播放源：应用名 + 图标（卡片右上角，与播放/暂停图标错开高度）
        RowLayout {
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.topMargin: 2
            anchors.rightMargin: 2
            spacing: 6
            visible: root.hasMedia && root.backend
                     && (root.backend.sourceName !== "" || root.backend.sourceIcon !== "")

            Text {
                Layout.maximumWidth: 168
                text: root.hasMedia && root.backend ? root.backend.sourceName : ""
                typography: Typography.Caption
                color: Colors.proxy.textSecondaryColor
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
                visible: text !== ""
            }

            Item {
                Layout.preferredWidth: 16
                Layout.preferredHeight: 16
                visible: root.hasMedia && root.backend && root.backend.sourceIcon !== ""

                Image {
                    anchors.fill: parent
                    anchors.margins: 1
                    source: root.hasMedia ? root.backend.sourceIcon : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    smooth: true
                    mipmap: true
                }
            }
        }
    }

    // ---------- 小组件自定义 ----------

    Text {
        Layout.fillWidth: true
        Layout.topMargin: 20
        typography: Typography.BodyStrong
        text: qsTr("小组件自定义")
    }

    // 媒体组件与歌词组件的设置按页签分组。
    // 插件自带 Pivot/PivotItem 组件（宿主 RinUI 没有 Pivot，见 Pivot.qml 头注释）。
    Pivot {
        id: widgetPivot
        objectName: "widgetPivot"
        Layout.fillWidth: true
        Layout.topMargin: 4

        PivotItem {
            objectName: "mediaSettingsPage"
            text: qsTr("媒体组件")
            iconName: "ic_fluent_album_20_regular"

            // 媒体组件封面右下角的播放源应用图标角标
            SettingCard {
                Layout.fillWidth: true
                Layout.topMargin: 4
                icon.name: "ic_fluent_app_generic_20_regular"
                title: qsTr("显示播放源图标")
                description: qsTr("在媒体组件的专辑封面右下角叠加显示正在播放的应用图标")

                Switch {
                    checked: root.config("show_source_badge", false)
                    onToggled: Configs.setPlugin(root.pluginId, "show_source_badge", checked)
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_paint_brush_20_regular"
                title: qsTr("渐变背景")
                description: qsTr("使用专辑封面的主色作为媒体组件背景")

                Switch {
                    checked: root.config("media_gradient_background", true)
                    onToggled: Configs.setPlugin(root.pluginId, "media_gradient_background", checked)
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_transparency_square_20_regular"
                title: qsTr("渐变背景浓度")
                description: qsTr("调整专辑主色渐变的透明度")

                Slider {
                    id: mediaGradientIntensity
                    Layout.preferredWidth: 156
                    from: 0
                    to: 100
                    stepSize: 1
                    value: root.config("media_gradient_intensity", 100)
                    onMoved: Configs.setPlugin(root.pluginId, "media_gradient_intensity",
                                                Math.round(value))
                }

                Text {
                    text: Math.round(mediaGradientIntensity.value) + "%"
                    typography: Typography.Caption
                    color: Colors.proxy.textSecondaryColor
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_data_bar_horizontal_20_regular"
                title: qsTr("背景进度显示")
                description: qsTr("在媒体组件背景中从左到右显示当前播放进度")

                Switch {
                    checked: root.config("media_background_progress", true)
                    onToggled: Configs.setPlugin(root.pluginId, "media_background_progress", checked)
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_timer_20_regular"
                title: qsTr("背景进度数字显示")
                description: qsTr("在媒体组件背景右下角显示已播放时间和总时长")

                Switch {
                    checked: root.config("media_background_progress_text", true)
                    onToggled: Configs.setPlugin(root.pluginId, "media_background_progress_text", checked)
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_text_description_20_regular"
                title: qsTr("副行内容")
                description: qsTr("选择媒体组件标题下方显示的信息")

                ComboBox {
                    id: mediaSubtitleCombo
                    textRole: "label"
                    model: ListModel {
                        ListElement { label: qsTr("歌手名"); value: "artist" }
                        ListElement { label: qsTr("进度数字"); value: "progress" }
                    }

                    property string currentContent: root.config("media_subtitle_content", "artist")
                    currentIndex: {
                        for (var i = 0; i < mediaSubtitleCombo.count; i++)
                            if (mediaSubtitleCombo.model.get(i).value === currentContent)
                                return i
                        return 0
                    }
                    onActivated: (index) => {
                        Configs.setPlugin(root.pluginId, "media_subtitle_content",
                                          mediaSubtitleCombo.model.get(index).value)
                    }
                }
            }
        }

        PivotItem {
            objectName: "lyricSettingsPage"
            text: qsTr("歌词组件")
            iconName: "ic_fluent_slide_text_20_regular"

            SettingCard {
                Layout.fillWidth: true
                Layout.topMargin: 4
                icon.name: "ic_fluent_paint_brush_20_regular"
                title: qsTr("渐变背景")
                description: qsTr("使用专辑封面的主色作为歌词组件背景")

                Switch {
                    checked: root.config("lyric_gradient_background", true)
                    onToggled: Configs.setPlugin(root.pluginId, "lyric_gradient_background", checked)
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_transparency_square_20_regular"
                title: qsTr("渐变背景浓度")
                description: qsTr("调整专辑主色渐变的透明度")

                Slider {
                    id: lyricGradientIntensity
                    Layout.preferredWidth: 156
                    from: 0
                    to: 100
                    stepSize: 1
                    value: root.config("lyric_gradient_intensity", 100)
                    onMoved: Configs.setPlugin(root.pluginId, "lyric_gradient_intensity",
                                                Math.round(value))
                }

                Text {
                    text: Math.round(lyricGradientIntensity.value) + "%"
                    typography: Typography.Caption
                    color: Colors.proxy.textSecondaryColor
                }
            }

            // 歌词源选择：改动立即生效（对当前歌曲重新抓取）
            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_cloud_arrow_down_20_regular"
                title: qsTr("歌词源")
                description: qsTr("「自动」按 QQ → 酷狗 → 网易云顺序取第一个匹配，优先逐字歌词")

                ComboBox {
                    id: sourceCombo
                    textRole: "label"
                    model: ListModel {
                        ListElement { label: qsTr("自动"); value: "auto" }
                        ListElement { label: qsTr("QQ音乐"); value: "qqmusic" }
                        ListElement { label: qsTr("酷狗音乐"); value: "kugou" }
                        ListElement { label: qsTr("网易云音乐"); value: "netease" }
                    }

                    property string currentSource: root.config("lyric_source", "auto")
                    currentIndex: {
                        for (var i = 0; i < sourceCombo.count; i++)
                            if (sourceCombo.model.get(i).value === currentSource)
                                return i
                        return 0
                    }
                    onActivated: (index) => {
                        Configs.setPlugin(root.pluginId, "lyric_source",
                                          sourceCombo.model.get(index).value)
                    }
                }
            }

            SettingCard {
                Layout.fillWidth: true
                icon.name: "ic_fluent_translate_20_regular"
                title: qsTr("副行内容")
                description: qsTr("选择歌词组件原文旁显示的内容")

                ComboBox {
                    id: lyricSubtitleCombo
                    textRole: "label"
                    model: ListModel {
                        ListElement {
                            label: qsTr("显示翻译，如没有就显示第二行歌词")
                            value: "translation_or_next"
                        }
                        ListElement {
                            label: qsTr("显示翻译，如没有就不显示")
                            value: "translation_or_none"
                        }
                        ListElement { label: qsTr("显示第二行歌词"); value: "next" }
                        ListElement { label: qsTr("不显示"); value: "none" }
                    }

                    property string currentContent: root.config(
                        "lyric_subtitle_content", "translation_or_next")
                    currentIndex: {
                        for (var i = 0; i < lyricSubtitleCombo.count; i++)
                            if (lyricSubtitleCombo.model.get(i).value === currentContent)
                                return i
                        return 0
                    }
                    onActivated: (index) => {
                        Configs.setPlugin(root.pluginId, "lyric_subtitle_content",
                                          lyricSubtitleCombo.model.get(index).value)
                    }
                }
            }
        }
    }
}
