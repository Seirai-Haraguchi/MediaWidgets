"""反探针：故意改坏实现，确认新动画断言真的会 FAIL，然后还原。

约定（见项目记忆）：改坏 → 必须 FAIL → 还原。探针必须打在**真实判据**上，
否则改坏了还绿，等于没测。

用法：./.venv312/Scripts/python.exe _antiprobe_anim.py
"""

import io
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent
QML = PLUGIN_DIR / "qml" / "LyricsWidget.qml"
TEST = PLUGIN_DIR / "_test_lyrics_widget.py"
PYTHON = PLUGIN_DIR / ".venv312" / "Scripts" / "python.exe"

# (说明, 原文, 替换, 期望 FAIL 时出现的关键字)
MUTATIONS = [
    (
        "去掉行快照：直接绑后端 words（旧行在通知到达前就没了 → 无从滑出）",
        "            words: root.shownWords\n",
        "            words: backend ? backend.words : []\n",
        "换行送出阶段就换掉了词表",
    ),
    (
        "去掉换歌过渡的可见性并入（idle 一瞬就整组件退场淡出）",
        "                                       || (songTransitionHold && hasMedia)\n",
        "                                       || false\n",
        "换歌过渡期间组件必须保持可见",
    ),
    (
        "去掉兜底计时器（ready 后拿不到首行 → 整块永久透明）",
        "        interval: 450\n",
        "        interval: 100000\n",
        "应有兜底把内容恢复可见",
    ),
    (
        "去掉送出阶段的整行上抬（旧行只会淡出、不再滑出）",
        "            return -lineExitProgress * lineLiftPx\n",
        "            return 0\n",
        "换行送出阶段整行应明显向上抬起",
    ),
    (
        "去掉顶部歌名的换歌位移（只有歌词块在动）",
        "        transform: Translate { x: root.songSlideX }\n",
        "        transform: Translate { x: 0 }\n",
        "顶部歌名必须随换歌一起横扫",
    ),
    (
        "把 Material 强调减速换成线性缓动（失去非线性质感）",
        "        return bezierAxis(parameter, 0.7, 1)\n",
        "        return x\n",
        "换歌应为非线性强调减速曲线",
    ),
]


def run_test():
    result = subprocess.run(
        [str(PYTHON), str(TEST)],
        cwd=str(PLUGIN_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or "") + (result.stderr or "")


def main():
    original = io.open(QML, encoding="utf-8").read()
    failures = []
    try:
        for label, old, new, expected in MUTATIONS:
            if old not in original:
                print(f"SKIP: 探针锚点没找到 —— {label}")
                failures.append(label)
                continue
            broken = original.replace(old, new, 1)
            if broken == original:
                print(f"SKIP: 替换没有生效 —— {label}")
                failures.append(label)
                continue
            io.open(QML, "w", encoding="utf-8", newline="\n").write(broken)
            try:
                output = run_test()
            finally:
                io.open(QML, "w", encoding="utf-8", newline="\n").write(original)
            if expected in output:
                print(f"OK  : 改坏后如期 FAIL —— {label}")
            elif "PASS:" in output:
                print(f"BAD : 改坏后仍然 PASS（探针没打在真实判据上）—— {label}")
                failures.append(label)
            else:
                print(f"BAD : 改坏后 FAIL 但不是预期原因 —— {label}")
                for line in output.strip().splitlines()[-6:]:
                    print(f"        {line}")
                failures.append(label)
    finally:
        io.open(QML, "w", encoding="utf-8", newline="\n").write(original)

    print()
    if failures:
        print(f"反探针未通过 {len(failures)}/{len(MUTATIONS)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"反探针全部通过（{len(MUTATIONS)} 项改坏都如期 FAIL）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
