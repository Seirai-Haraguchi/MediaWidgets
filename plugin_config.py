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
    # 媒体组件专辑封面右下角的播放源应用图标角标开关
    show_source_badge: bool = False

    # 媒体组件背景
    media_gradient_background: bool = True
    media_gradient_intensity: int = 100
    media_background_progress: bool = True
    media_background_progress_text: bool = True
    # 媒体组件副行：artist / progress
    media_subtitle_content: str = "artist"

    # 歌词源：auto / qqmusic / kugou / netease（改源后对当前歌曲立即重抓）
    lyric_source: str = "auto"
    # 歌词组件背景
    lyric_gradient_background: bool = True
    lyric_gradient_intensity: int = 100
    # 歌词组件副行：translation_or_next / translation_or_none / next / none
    lyric_subtitle_content: str = "translation_or_next"
