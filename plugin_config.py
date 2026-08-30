"""
plugin_config.py
Media Widgets 插件自身的配置模型。

通过 api.config.register_plugin_model() 注册后：
- 首次运行把各字段默认值写进 configs.plugins.configs[pid]，
  QML 设置页用 Configs.data.plugins.configs[pid].<字段> 读初始状态；
- 运行时用户在设置页切换开关，经 Configs.setPlugin 写回同一字典并持久化；
- Python 侧（main.py 的 _live_config_getter）每次从该字典现读，
  保证开关改动立即生效（CW2 不会把字典变更同步回模型实例）。
"""

from ClassWidgets.SDK import ConfigBaseModel


class MediaWidgetsConfig(ConfigBaseModel):
    # 灵动通知歌词开关：关闭后不再把逐行歌词推送到 CW2 动态通知
    lyrics_enabled: bool = True
    # 歌词翻译（如有）显示开关：关闭后只推原文，翻译不进消息栏分栏
    show_translation: bool = True