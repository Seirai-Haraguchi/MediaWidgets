"""
Media Widgets
一个显示系统媒体信息并把歌词推送到动态通知的 Class Widgets 插件。
Windows 走 SMTC，Linux 走 MPRIS。
"""

import sys

from loguru import logger
from ClassWidgets.SDK import CW2Plugin, PluginAPI

from plugin_config import MediaWidgetsConfig


class Plugin(CW2Plugin):
    def __init__(self, api: PluginAPI):
        super().__init__(api)
        # 请在此导入第三方库 / Import third-party libraries here
        self._backend = None
        self._lyrics_pusher = None
        self._config = MediaWidgetsConfig()

    def on_load(self):
        super().on_load()
        logger.info("Media Widgets: on_load() called")

        # 注册插件配置模型：把默认值落进 configs.plugins.configs[pid]，
        # QML 设置页由此读到初始状态；运行时开关经 Configs.setPlugin 写回同一字典
        try:
            if self.pid:
                self.api.config.register_plugin_model(self.pid, self._config)
        except Exception as e:
            logger.warning(f"Media Widgets: register config model failed: {e}")

        # 注册同名设置页：挂在 CW2 设置 → 插件 → Media Widgets
        try:
            self.api.ui.register_settings_page(
                qml_path="qml/MediaWidgetsSettings.qml",
                title="Media Widgets",
                icon="ic_fluent_music_note_2_20_regular",
            )
        except Exception as e:
            logger.warning(f"Media Widgets: register settings page failed: {e}")

        # 运行时注入：把动态通知歌词区撑宽（幂等自愈，CW2 更新后自动重打）
        try:
            from PySide6.QtCore import QTimer
            from qml_patch import apply_notification_width_patch
            apply_notification_width_patch()
            QTimer.singleShot(2000, apply_notification_width_patch)
        except Exception as e:
            logger.warning(f"Media Widgets: notification width patch failed: {e}")

        # 创建 backend 对象（延迟导入，数据源不可用时也不阻止 widget 注册）
        try:
            if sys.platform == "win32":
                from smtc_backend import SmtcBackend
                self._backend = SmtcBackend()
                logger.info("Media Widgets: SmtcBackend created")
            else:
                from mpris_backend import MprisBackend
                self._backend = MprisBackend()
                logger.info("Media Widgets: MprisBackend created")
        except Exception as e:
            logger.error(f"Media Widgets: backend init failed: {e}")
            self._backend = None

        # 注册 widget（无论 backend 是否成功都要注册）
        self.api.widgets.register(
            widget_id="com.seiraiharaguchi.mediawidgets.widget",
            name="Media Widget",
            qml_path="qml/MediaWidget.qml",
            backend_obj=self._backend,
        )
        logger.info("Media Widgets: widget registered")

        # 把媒体后端暴露给「设置 → 插件 → Media Widgets」页面，
        # 使设置页能实时显示正在播放信息（此前该 key 上注册的是插件实例自身）
        if self._backend is not None and self.pid:
            try:
                from src.core.plugin.bridge import PluginBackendBridge
                PluginBackendBridge.register_backend(self.pid, self._backend)
            except Exception as e:
                logger.debug(f"Media Widgets: expose backend to settings page failed: {e}")

        # 延迟启动媒体后端（确保 Qt 事件循环已启动）
        if self._backend is not None:
            try:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1000, self._backend.start)
                logger.info("Media Widgets: scheduled backend.start() in 1s")
            except Exception as e:
                logger.error(f"Media Widgets: backend start failed: {e}")

            # 滚动歌词：网易云搜索匹配 → 逐行推送到 CW2 动态通知
            try:
                provider = self.api.notification.get_provider(
                    "com.seiraiharaguchi.mediawidgets.lyrics",
                    name="Media Widgets Lyrics",
                )
                from lyrics_pusher import LyricsPusher
                self._lyrics_pusher = LyricsPusher(
                    provider, self._backend, self._live_config_getter()
                )
                logger.info("Media Widgets: lyrics pusher ready")
            except Exception as e:
                logger.error(f"Media Widgets: lyrics pusher init failed: {e}")
        else:
            logger.warning("Media Widgets: backend is None, skipping start")

    def _live_config_getter(self):
        """返回实时读取本插件配置的函数。

        QML 设置页的开关经 Configs.setPlugin 写进 configs.plugins.configs[pid]
        （CW2 不会把字典变更同步回注册的模型实例），所以 Python 侧每次都从
        配置管理器现读，保证开关立即生效。读取失败返回 None，由调用方回退默认值。
        """
        pid = self.pid
        try:
            configs = self.api.globalconfig.configs
        except Exception as e:
            logger.warning(f"Media Widgets: access config manager failed: {e}")
            return lambda key: None

        def getter(key):
            try:
                section = configs.plugins.configs.get(pid)
                if not isinstance(section, dict):
                    return None
                return section.get(key)
            except Exception:
                return None

        return getter

    def on_unload(self):
        logger.info("Media Widgets: on_unload()")
