"""
Media Widgets
一个用于显示 Windows SMTC 媒体信息的 Class Widgets 插件。
"""

from loguru import logger
from ClassWidgets.SDK import CW2Plugin, PluginAPI


class Plugin(CW2Plugin):
    def __init__(self, api: PluginAPI):
        super().__init__(api)
        # 请在此导入第三方库 / Import third-party libraries here
        self._backend = None
        self._lyrics_pusher = None

    def on_load(self):
        super().on_load()
        logger.info("Media Widgets: on_load() called")

        # 运行时注入：把动态通知歌词区撑宽（幂等自愈，CW2 更新后自动重打）
        try:
            from PySide6.QtCore import QTimer
            from qml_patch import apply_notification_width_patch
            apply_notification_width_patch()
            QTimer.singleShot(2000, apply_notification_width_patch)
        except Exception as e:
            logger.warning(f"Media Widgets: notification width patch failed: {e}")

        # 创建 backend 对象（延迟导入，避免 winrt 不可用时阻止 widget 注册）
        try:
            from smtc_backend import SmtcBackend
            self._backend = SmtcBackend()
            logger.info("Media Widgets: SmtcBackend created")
        except Exception as e:
            logger.error(f"Media Widgets: SMTC backend init failed: {e}")
            self._backend = None

        # 注册 widget（无论 backend 是否成功都要注册）
        self.api.widgets.register(
            widget_id="com.seiraiharaguchi.mediawidgets.widget",
            name="Media Widget",
            qml_path="qml/MediaWidget.qml",
            backend_obj=self._backend,
        )
        logger.info("Media Widgets: widget registered")

        # 延迟启动 SMTC 轮询（确保 Qt 事件循环已启动）
        if self._backend is not None:
            try:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1000, self._backend.start)
                logger.info("Media Widgets: scheduled backend.start() in 1s")
            except Exception as e:
                logger.error(f"Media Widgets: SMTC backend start failed: {e}")

            # 滚动歌词：网易云搜索匹配 → 逐行推送到 CW2 动态通知
            try:
                provider = self.api.notification.get_provider(
                    "com.seiraiharaguchi.mediawidgets.lyrics",
                    name="Media Widgets Lyrics",
                )
                from lyrics_pusher import LyricsPusher
                self._lyrics_pusher = LyricsPusher(provider, self._backend)
                logger.info("Media Widgets: lyrics pusher ready")
            except Exception as e:
                logger.error(f"Media Widgets: lyrics pusher init failed: {e}")
        else:
            logger.warning("Media Widgets: backend is None, skipping start")

    def on_unload(self):
        logger.info("Media Widgets: on_unload()")
