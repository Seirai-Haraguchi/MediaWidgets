"""验证 qq_des.py：抓真实 QRC 加密载荷 → 解密 → 解析出逐字歌词。"""
import json
import re
import urllib.request

import qq_des

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def qq_search(query):
    body = {
        "music.search.SearchCgiService": {
            "method": "DoSearchForQQMusicDesktop",
            "module": "music.search.SearchCgiService",
            "param": {"num_per_page": 10, "page_num": 1, "query": query, "search_type": 0},
        }
    }
    req = urllib.request.Request(
        "https://u.y.qq.com/cgi-bin/musicu.fcg",
        data=json.dumps(body).encode(), method="POST",
        headers={"User-Agent": UA, "Referer": "https://y.qq.com/",
                 "Origin": "https://y.qq.com", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return (data.get("music.search.SearchCgiService", {}).get("data", {})
            .get("body", {}).get("song", {}).get("list", []))


songs = qq_search("晴天 周杰伦")
song = songs[0]
print("song:", song.get("title"), song.get("id"))

url = f"https://c.y.qq.com/qqmusic/fcgi-bin/lyric_download.fcg?version=15&miniversion=82&lrctype=4&musicid={song['id']}"
req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://y.qq.com/"})
with urllib.request.urlopen(req, timeout=10) as r:
    text = r.read().decode("utf-8", errors="replace")

# 全部 CDATA 块（可能含原文/翻译/罗马音多个 content）
cdatas = re.findall(r"<!\[CDATA\[(.*?)\]\]>", text, re.S)
print(f"CDATA blocks: {len(cdatas)}")
for i, c in enumerate(cdatas):
    c = c.strip()
    print(f"  [{i}] len={len(c)} hex={bool(re.fullmatch(r'[0-9a-fA-F]+', c))}")

if cdatas:
    try:
        qrc = qq_des.decrypt_qrc_payload(cdatas[0])
        print(f"\nDECRYPTED OK, len={len(qrc)}")
        lines = qrc.splitlines()
        print(f"lines: {len(lines)}")
        for ln in lines[:14]:
            print("  ", ln[:100])
    except Exception as e:
        print(f"\nDECRYPT FAILED: {type(e).__name__}: {e}")
        # 打印解密后的前几个字节看是不是 zlib 头
        import binascii
        payload = binascii.unhexlify("".join(cdatas[0].split()))
        dec = qq_des.QqTripleDesDecryptor(qq_des._QRC_KEY).decrypt_ecb(payload)
        print("plain head bytes:", dec[:16].hex())
