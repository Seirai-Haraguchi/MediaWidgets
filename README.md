# 此插件仅供 Windows 平台使用！！！！！

# Media Widgets

Media Widgets 是为 [Class Widgets 2](https://github.com/RinLit-233-shiroko/Class-Widgets-2) 设计的插件，用于以小组件形式在屏幕上显示 Windows SMTC 媒体信息。

## 功能

- 媒体小组件：显示当前歌曲标题、歌手、专辑封面与播放进度
- 专辑主色渐变背景：从封面提取两个主色渲染半透明渐变，进度以遮罩横向填充
- 滚动歌词推送：自动到网易云音乐搜索匹配当前歌曲的歌词，按播放进度把歌词逐行实时推送到「动态通知」小组件（无提示音）。有翻译时原文进标题栏、翻译进消息栏分栏显示，无翻译时仅显示原文一行。需要在桌面添加 CW2 自带的「动态通知」小组件才能看到；不想用的时候在 CW2 设置的通知页里关掉 "Media Widgets Lyrics" 这个来源即可。

> 说明：CW2 动态通知的歌词区宽度上限固定为 200px，超宽文本只能跑马灯滚动。本插件在加载时会**运行时注入** CW2 核心组件 `dynamicNotification.qml`，把歌词区上限提到 480px——能放下的歌词直接撑宽静态显示，更长的才滚动。补丁幂等且自愈：CW2 更新覆盖文件后，插件下次加载会自动重新打上；若组件结构发生变化则静默跳过、绝不破坏文件。卸载插件不会回滚该文件。

## 截图

### 媒体小组件

默认模式显示歌曲标题、歌手、专辑封面与播放进度，背景为封面提取的半透明主色渐变：

![媒体小组件](docs/1.png)

### 动态通知歌词

歌词与翻译分栏显示在动态通知的标题与消息栏（有翻译时双栏，无翻译时仅原文一行），默认模式与迷你模式均可使用：

| | 有歌词 | 无歌词 |
| --- | --- | --- |
| 默认模式 | ![默认模式·有歌词](docs/Default%20Mode%20With%20Lyrics%20Dynamic%20Notification.png) | ![默认模式·无歌词](docs/Default%20Mode%20Without%20Lyrics%20Dynamic%20Notification.png) |
| 迷你模式 | ![迷你模式·有歌词](docs/Mini%20Mode%20With%20Lyrics%20Dynamic%20Notification.png) | ![迷你模式·无歌词](docs/Mini%20Mode%20Without%20Lyrics%20Dynamic%20Notification.png) |

## 许可

本项目基于 MIT 协议开源。

