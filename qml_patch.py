"""
动态通知撑宽注入：运行时把 CW2 核心组件 dynamicNotification.qml 的歌词区
宽度上限从默认 200 提到 480（能放下就静态显示，更长才跑马灯）。

这是 CW2 核心 QML，插件没有官方 API 可改，只能运行时注入源文件。
补丁幂等且自愈：CW2 更新覆盖文件后，下次插件加载会自动重新打上；
结构变化导致匹配失败时静默跳过，绝不破坏文件。
"""

import re
from pathlib import Path

from loguru import logger

_TARGET = "dynamicNotification.qml"
_DEFAULT_MAX_WIDTH = 480


def find_notification_qml():
    """定位动态通知组件 QML，按可靠性依次尝试。"""
    try:
        from src.core.directories import QML_PATH
        p = Path(QML_PATH) / "widgets" / _TARGET
        if p.exists():
            return p
    except Exception:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "qml" / "widgets" / _TARGET
        if cand.exists():
            return cand
    return None


def _replace_maxwidth(source, label_id, max_width):
    m = re.search(rf"(id:\s*{label_id}[\s\S]*?maximumWidth:\s*)\d+", source)
    if m:
        return source[: m.start()] + f"{m.group(1)}{max_width}" + source[m.end():]
    return None


def _insert_maxwidth(source, label_id, anchor, max_width):
    m = re.search(rf"(id:\s*{label_id}[\s\S]*?)(text:\s*{anchor})", source)
    if m:
        head, mark = m.group(1), m.group(2)
        return (
            f"{head}{mark}\n"
            f"                maximumWidth: {max_width}   // Media Widgets: 撑宽优先"
            + source[m.end():]
        )
    return None


def patch_source(source: str, max_width: int = _DEFAULT_MAX_WIDTH) -> str:
    # 原文/翻译分别进标题槽、消息槽，两个 label 都撑宽；匹配失败保持原样
    for label_id, anchor in (("messageLabel", "notificationMessage"), ("titleLabel", "editMode")):
        out = _replace_maxwidth(source, label_id, max_width)
        if out is None:
            out = _insert_maxwidth(source, label_id, anchor, max_width)
        if out is not None:
            source = out
    return source


def apply_notification_width_patch(max_width: int = _DEFAULT_MAX_WIDTH):
    qml = find_notification_qml()
    if qml is None:
        logger.debug("Media Widgets: dynamicNotification.qml not found, patch skipped")
        return False
    try:
        original = qml.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Media Widgets: read {qml} failed: {e}")
        return False
    # 两个 label 都已注入则视为完成；否则重新补全（幂等自愈）
    patched = patch_source(original, max_width)
    if patched == original:
        return f"maximumWidth: {max_width}" in original
    try:
        qml.write_text(patched, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Media Widgets: write {qml} failed: {e}")
        return False
    logger.info(
        f"Media Widgets: patched {qml} (titleLabel/messageLabel maximumWidth -> {max_width})"
    )
    return True
