import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI

// Media Widgets 插件的同名设置页
// 由 main.py 在 on_load 时经 api.ui.register_settings_page 注册，
// 挂在 CW2 设置 → 插件 → Media Widgets 下。
//
// 与 CW2 内置 Notification.qml 同结构（FluentPage 直接放置设置项）；
// 配置经 Configs.setPlugin 写回，Python 侧的 MediaWidgetsConfig 同步生效。
FluentPage {
    id: root
    horizontalPadding: 0
    wrapperWidth: width - 42 * 2
    spacing: 4
    title: qsTr("Media Widgets")

    // 插件 id 固定，避免依赖导航是否把 pluginId 注入页面
    property string pluginId: "com.seiraiharaguchi.mediawidgets"
    // 媒体后端由 main.py 在 on_load 注册进 PluginBackendBridge，
    // 可取到实时在播数据（title/artist/art/progress 等）
    property var backend: typeof PluginBackendBridge !== "undefined"
                          ? PluginBackendBridge.get_backend(pluginId) : null

    function config(key, fallback) {
        var cfg = Configs.data.plugins && Configs.data.plugins.configs
        if (!cfg || !cfg[root.pluginId]) return fallback
        var v = cfg[root.pluginId][key]
        return v === undefined ? fallback : v
    }

    Text {
        Layout.fillWidth: true
        Layout.topMargin: 8
        typography: Typography.BodyStrong
        text: qsTr("正在播放")
    }

    // 正在播放信息卡片：封面 + 标题/艺人 + 进度，随 backend 实时刷新
    Rectangle {
        Layout.fillWidth: true
        Layout.topMargin: 4
        Layout.preferredHeight: 84
        radius: 8
        color: Colors.proxy.controlAltTertiaryColor

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 12
            anchors.bottomMargin: 12
            spacing: 14

            Rectangle {
                Layout.preferredWidth: 56
                Layout.preferredHeight: 56
                radius: 12
                color: "transparent"

                Image {
                    anchors.fill: parent
                    source: root.backend && root.backend.art ? root.backend.art : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    clip: true
                    visible: source !== ""
                }
                // 无封面时音符占位
                Rectangle {
                    anchors.fill: parent
                    radius: 12
                    color: Qt.alpha(root.backend ? root.backend.accentColor : "#9AA0A6", 0.18)
                    visible: !(root.backend && root.backend.art)
                    Text {
                        anchors.centerIn: parent
                        text: qsTr("\u266A")
                        color: Colors.proxy.textSecondaryColor
                        font.pixelSize: 24
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: root.backend && root.backend.title
                          ? root.backend.title : qsTr("未在播放")
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    typography: Typography.BodyStrong
                }
                Text {
                    Layout.fillWidth: true
                    text: root.backend && root.backend.artist
                          ? root.backend.artist : qsTr("当前没有正在播放的媒体")
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    typography: Typography.Caption
                    color: Colors.proxy.textSecondaryColor
                }
            }

            ColumnLayout {
                Layout.preferredWidth: 88
                spacing: 2
                Text {
                    Layout.alignment: Qt.AlignRight
                    text: root.backend ? root.backend.positionText : ""
                    color: Colors.proxy.textSecondaryColor
                    typography: Typography.Caption
                    visible: root.backend && root.backend.durationText !== "0:00"
                }
                Text {
                    Layout.alignment: Qt.AlignRight
                    text: root.backend ? root.backend.durationText : ""
                    color: Colors.proxy.textSecondaryColor
                    typography: Typography.Caption
                    visible: root.backend && root.backend.durationText !== "0:00"
                }
            }
        }

        // 底部主色进度条
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 12
            height: 3
            radius: 1.5
            color: Colors.proxy.controlBorderColor
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * (root.backend ? root.backend.progress : 0)
                radius: 1.5
                color: root.backend ? root.backend.accentColor : "#9AA0A6"
                Behavior on width {
                    NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
                }
            }
        }
    }

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
        icon.name: "ic_fluent_notification_2_20_regular"
        title: qsTr("灵动通知歌词")
        description: qsTr("把逐行歌词实时推送到动态通知小组件")

        Switch {
            Component.onCompleted: checked = root.config("lyrics_enabled", true)
            onCheckedChanged: Configs.setPlugin(root.pluginId, "lyrics_enabled", checked)
        }
    }

    // 歌词翻译（如有）显示开关
    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_translate_20_regular"
        title: qsTr("显示歌词翻译")
        description: qsTr("有翻译时，译文与原文分栏显示在动态通知中")

        Switch {
            Component.onCompleted: checked = root.config("show_translation", true)
            onCheckedChanged: Configs.setPlugin(root.pluginId, "show_translation", checked)
        }
    }
}