"""
plugin_config.py
Media Widgets 插件自身的配置模型。

通过 api.config.register_plugin_model() 注册后：
- 首次运行把各字段默认值写进 configs.plugins.configs[pid]，
  QML 设置页用 Configs.data.plugins.configs[pid].<字段> 读初始状态；
- 运行时用户在设置页改动，经 Configs.setPlugin 写回同一字典并持久化；
- Python 侧（main.py 的 _live_config_getter）每次从该字典现读，
  保证改动立即生效（CW2 不会把字典变更同步回模型实例）。
"""

from ClassWidgets.SDK import ConfigBaseModel


class MediaWidgetsConfig(ConfigBaseModel):
    # 歌词源：auto / qqmusic / kugou / netease（改源后对当前歌曲立即重抓）
    lyric_source: str = "auto"
    # 歌词翻译（如有）显示开关：开启时歌词组件原文下方显示译文，
    # 关闭或无翻译时显示下一行歌词预览
    show_translation: bool = True
