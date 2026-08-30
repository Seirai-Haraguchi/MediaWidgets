"""
plugin_config.py
Media Widgets 插件自身的配置模型。

通过 api.config.register_plugin_model() 注册后：
- QML 设置页用 Configs.data.plugins.configs[pid].<字段> 读取、
  Configs.setPlugin(pid, "<字段>", 值) 写入；
- 插件 Python 侧直接读实例属性（运行时同步）。
"""

from ClassWidgets.SDK import ConfigBaseModel


class MediaWidgetsConfig(ConfigBaseModel):
    # 灵动通知歌词开关：关闭后不再把逐行歌词推送到 CW2 动态通知
    lyrics_enabled: bool = True
    # 歌词翻译（如有）显示开关：关闭后只推原文，翻译不进消息栏分栏
    show_translation: bool = True