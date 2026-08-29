"""Windows 回归：验证基类抽取后 SmtcBackend 的继承行为与原一致。"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QBuffer, QCoreApplication, QIODevice
from PySide6.QtGui import QImage, QColor

app = QCoreApplication([])

from smtc_backend import SmtcBackend


def png_bytes(size=64, color="#C0392B"):
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


fails = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        fails.append(name)


# 1. 属性与信号
b = SmtcBackend()
events = []
b.songChanged.connect(lambda t, a: events.append((t, a)))
b._apply_update("title1", "artist1", "", 1000, 200000, "#111111", "#222222")
check("title", b.title == "title1", repr(b.title))
check("artist", b.artist == "artist1", repr(b.artist))
check("durationText", b.durationText == "3:20", repr(b.durationText))
check("accentColor", b.accentColor == "#111111")
check("accentColor2", b.accentColor2 == "#222222")
check("songChanged fired", events == [("title1", "artist1")], str(events))

# 2. 换歌触发 songChanged
b._apply_update("title2", "artist2", "", 3000, 200000, "#111111", "#222222")
check("songChanged re-fired", events[-1] == ("title2", "artist2"), str(events))

# 3. 进度插值：播放中随时间前进
b._apply_playback(4, 1.0)          # Playing
b._apply_timeline(10000, 200000)   # pos=10s
p0 = b.current_position_ms()
time.sleep(0.3)
p1 = b.current_position_ms()
check("interp advances while playing", p1 > p0, f"{p0} -> {p1}")
b._apply_playback(0, 1.0)          # Paused
p2 = b.current_position_ms()
time.sleep(0.2)
p3 = b.current_position_ms()
check("interp frozen when paused", p2 == p3, f"{p2} vs {p3}")

# 4. 专辑图处理 + 主色提取
raw = png_bytes(300, "#C0392B")  # 纯红
url = b._rounded_png_data_url(raw)
check("art data URL", url.startswith("data:image/png;base64,"))
a1, a2 = b._extract_palette(url)
check("palette primary reddish", a1 == "#C03030" or a1.startswith("#C0"), f"a1={a1} a2={a2}")

# 5. process_art_bytes 缓存
url1 = b.process_art_bytes(raw)
url2 = b.process_art_bytes(raw)
check("art cache stable", url1 == url2 and b._last_art_hash is not None)
check("art cache url set", b._last_art_url != "")

# 6. 空状态清除
b._apply_update("", "", "", 0, 0, *b._last_palette)
check("empty clears title", b.title == "" and b.artist == "")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
