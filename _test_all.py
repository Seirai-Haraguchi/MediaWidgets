"""跑全套 `_test_*.py` 回归测试并汇总结果。

排除自身（名字也匹配 `_test_*.py`，否则会无限递归）。

判定约定（各套件统一）：
- 失败：打印 `FAIL: ...`（带冒号）或 `FAILURES: <非 none>`；
- 成功：打印 `FAILURES: none`。

所以**不能**用简单的 `"FAIL" not in output`——成功摘要里的
`FAILURES: none` 同样含 `FAIL` 子串，会把全绿的套件误判为失败。
活网脚本（_test_des / _test_e2e）只打印抓取到的数据、不给标记，
按「退出码为 0 且无失败标记」处理。

用法：./.venv312/Scripts/python.exe _test_all.py
"""

import re
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent
PYTHON = PLUGIN_DIR / ".venv312" / "Scripts" / "python.exe"
SELF = Path(__file__).name

# `FAIL:` 必须带冒号，才不会误伤 `FAILURES:`；`FAILURES:` 后面接 none 才算过。
_FAIL_LINE = re.compile(r"^FAIL:", re.MULTILINE)
_FAILURES = re.compile(r"^FAILURES:\s*(.+)$", re.MULTILINE)


def suite_passed(output: str, returncode: int) -> bool:
    if returncode != 0:
        return False
    if _FAIL_LINE.search(output):
        return False
    summary = _FAILURES.search(output)
    if summary and summary.group(1).strip().lower() != "none":
        return False
    return True


def main():
    tests = sorted(p.name for p in PLUGIN_DIR.glob("_test_*.py") if p.name != SELF)
    failed = []
    for name in tests:
        result = subprocess.run(
            [str(PYTHON), str(PLUGIN_DIR / name)],
            cwd=str(PLUGIN_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout or "") + (result.stderr or "")
        ok = suite_passed(output, result.returncode)
        print(f"{'PASS' if ok else 'FAIL'}  {name}  (exit={result.returncode})")
        if not ok:
            failed.append(name)
            for line in [ln for ln in output.strip().splitlines() if ln.strip()][-8:]:
                print(f"        {line}")
    print()
    if failed:
        print(f"失败 {len(failed)}/{len(tests)}：{', '.join(failed)}")
        return 1
    print(f"全部 {len(tests)} 个测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
