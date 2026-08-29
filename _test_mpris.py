"""MPRIS 后端逻辑单测：注入假播放器，验证状态解析、选路、封面与插值。"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QBuffer, QCoreApplication, QIODevice
from PySide6.QtDBus import QDBusVariant
from PySide6.QtGui import QImage, QColor

app = QCoreApplication([])

from mpris_backend import MprisBackend, _IFACE_PLAYER


def png_bytes(size=64, color="#2ECC71"):
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


class FakeIface:
    """模拟 QDBusInterface.property(name)。"""

    def __init__(self, props):
        self._props = props

    def set(self, name, value):
        self._props[name] = value

    def property(self, name):
        return self._props.get(name)


SVC = "org.mpris.MediaPlayer2.fake"
SVC2 = "org.mpris.MediaPlayer2.fake2"


def make_backend(iface, svc=SVC):
    b = MprisBackend()
    b._ifaces[svc] = iface
    b._players[svc] = time.monotonic()
    b._session = iface
    b._session_service = svc
    return b


# 1. 基本状态解析（dict 值直接给 Python 类型，模拟 _unwrap 之后）
iface = FakeIface({
    "PlaybackStatus": "Playing",
    "Rate": 1.0,
    "Position": 65000000,  # 65s in μs
    "Metadata": {
        "xesam:title": "Lemon",
        "xesam:artist": ["Kenshi Yonezu"],
        "mpris:length": 261000000,  # 261s in μs
        "mpris:artUrl": "",
    },
})
b = make_backend(iface)
song_events = []
b.songChanged.connect(lambda t, a: song_events.append((t, a)))
b._refresh()
check("title", b.title == "Lemon", repr(b.title))
check("artist list joined", b.artist == "Kenshi Yonezu", repr(b.artist))
check("durationText", b.durationText == "4:21", repr(b.durationText))
check("position ms", b._position_ms == 65000, f"{b._position_ms}")
check("songChanged fired", song_events == [("Lemon", "Kenshi Yonezu")], str(song_events))

# 2. 播放/暂停切换
iface.set("PlaybackStatus", "Paused")
b._refresh()
check("paused -> not playing", b._playing is False)
iface.set("PlaybackStatus", "Playing")
b._refresh()
check("playing -> playing", b._playing is True)

# 3. Seeked 事件
b._on_seeked(SVC, 12345000)
check("seeked updates position", 12300 <= b._position_ms <= 12400, f"{b._position_ms}")

# 4. 活跃播放器选择：优先 Playing
ifaceA = FakeIface({"PlaybackStatus": "Paused", "Metadata": {"xesam:title": "A"}})
ifaceB = FakeIface({"PlaybackStatus": "Playing", "Metadata": {"xesam:title": "B"}})
b2 = make_backend(ifaceA, SVC)
b2._players[SVC2] = time.monotonic() + 100
b2._ifaces[SVC2] = ifaceB
b2._session_service = SVC2
b2._session = ifaceB
b2._refresh()
b2._refresh_active()
check("active prefers playing", b2._active == SVC2, f"active={b2._active}")

# 5. 空播放器集 → 清空状态
b3 = MprisBackend()
b3._players = {}
b3._refresh()
check("empty players clears", b3.title == "" and b3._active is None)

# 6. _unwrap：QDBusVariant 包装
v = QDBusVariant("Playing")
check("unwrap QDBusVariant", MprisBackend._unwrap(v) == "Playing")
d = {"xesam:title": QDBusVariant("T"), "xesam:artist": QDBusVariant(["X", "Y"])}
ud = MprisBackend._unwrap(d)
check("unwrap dict", ud == {"xesam:title": "T", "xesam:artist": ["X", "Y"]}, str(ud))

# 7. 封面解析：data: URI 与 file: URI
with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    f.write(png_bytes(64, "#2ECC71"))
    art_path = Path(f.name)
b4 = make_backend(FakeIface({
    "PlaybackStatus": "Playing",
    "Rate": 1.0,
    "Position": 0,
    "Metadata": {
        "xesam:title": "Greensleeves",
        "xesam:artist": ["X"],
        "mpris:length": 100000000,
        "mpris:artUrl": art_path.as_uri(),
    },
}))
b4._refresh()
check("file art applied", b4._art.startswith("data:image/png;base64,"), f"len={len(b4._art)}")
check("file art palette", b4.accentColor != "#9AA0A6", f"{b4.accentColor}")
b4._handle_metadata({"xesam:title": "G2", "mpris:artUrl": "data:image/png;base64," + "AA=="})
check("data art decoded (bad img -> no art)", b4._art == "" or b4._art.startswith("data:"))

# 8. 过期封面丢弃：歌已切换后 _artReady 不回填
b5 = make_backend(FakeIface({
    "PlaybackStatus": "Playing", "Rate": 1.0, "Position": 0,
    "Metadata": {"xesam:title": "Old", "mpris:length": 100000000},
}), SVC)
b5._title = "New"
b5._artist = "Y"
b5._on_art_ready("data:image/png;base64," + "AA==", ("Old", "X"))
check("stale art dropped", b5._art == "" or not b5._art.startswith("data:image"), f"art={b5._art!r}")

art_path.unlink(missing_ok=True)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
