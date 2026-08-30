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

        ColumnLayout {
            anchors.fill: parent
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
    }

    // ---------- 歌词 ----------

    Text {
        Layout.fillWidth: true
        Layout.topMargin: 20
        typography: Typography.BodyStrong
        text: qsTr("歌词")
    }

    // 灵动通知歌词开关
    SettingCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        icon.name: "ic_fluent_alert_on_20_regular"
        title: qsTr("灵动通知歌词")
        description: qsTr("把逐行歌词实时推送到动态通知小组件")

        Switch {
            checked: root.config("lyrics_enabled", true)
            onToggled: Configs.setPlugin(root.pluginId, "lyrics_enabled", checked)
        }
    }

    // 歌词翻译（如有）显示开关
    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_translate_20_regular"
        title: qsTr("显示歌词翻译")
        description: qsTr("有翻译时，译文与原文分栏显示在动态通知中")

        Switch {
            checked: root.config("show_translation", true)
            onToggled: Configs.setPlugin(root.pluginId, "show_translation", checked)
        }
    }
}
