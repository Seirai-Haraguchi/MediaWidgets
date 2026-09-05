"""
lyrics_providers.py
多歌词源统一框架：网易云音乐（LRC 行级）、QQ音乐（QRC 逐字）、酷狗音乐（KRC 逐字）。

统一输出 LyricsDocument（行 + 逐字时间戳 + 翻译），供歌词小组件按播放进度渲染。
接口参考 MediaIsland（bywhite0/MediaIsland）的 Provider 架构：
- 每个源各自搜索 → 打分选歌 → 抓取解析；
- QQ 的 QRC 载荷为定制 S-box 的 Triple-DES 加密（解密在 qq_des.py）；
- 酷狗的 KRC 载荷为 XOR + zlib（纯标准库即可解开）。

纯逻辑、无 Qt 依赖，便于独立测试。网络异常向上抛出，由调用方决定缓存策略。
"""

import base64
import json
import re
import time
import urllib.parse
import urllib.request
import zlib

import netease_lyrics

_TIMEOUT = 8
_RETRIES = 2

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 歌词源显示名（设置页与日志用）
SOURCE_NAMES = {
    "qqmusic": "QQ音乐",
    "kugou": "酷狗音乐",
    "netease": "网易云音乐",
}

# 自动模式下的尝试顺序：逐字覆盖优先
AUTO_ORDER = ("qqmusic", "kugou", "netease")

# 换歌后各源的匹配阈值：网易云沿用 netease_lyrics 的 5.5 分制（≥3.0 接受），
# QQ/酷狗候选自带秒级时长，按 MediaIsland 思路用标题+艺人+时长近似折算成 5.5 分制
_ACCEPT = 3.0


class LyricWord:
    __slots__ = ("start_ms", "end_ms", "text")

    def __init__(self, start_ms, end_ms, text):
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.text = text


class LyricLine:
    __slots__ = ("start_ms", "end_ms", "text", "words", "translation")

    def __init__(self, start_ms, end_ms, text, words=None, translation=None):
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.text = text
        self.words = words or []
        self.translation = translation


class LyricsDocument:
    __slots__ = ("lines", "source", "song_name")

    def __init__(self, lines, source, song_name=""):
        self.lines = lines
        self.source = source
        self.song_name = song_name

    @property
    def has_word_timing(self):
        return any(line.words for line in self.lines)


# ---- HTTP 基础 ----

def _http_json(url, headers=None, data=None, retries=_RETRIES):
    last_err = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers={"User-Agent": _UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.load(resp)
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise last_err


def _http_text(url, headers=None, data=None):
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": _UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---- 打分（复用网易云的归一化与相似度，换算到统一 5.5 分制） ----

def _score_candidate(title, artist, got_title, got_artist, duration_ms, got_duration_ms):
    t = netease_lyrics._title_score(title, got_title)
    a = netease_lyrics._artist_score(artist, [got_artist] if got_artist else [])
    d = netease_lyrics._duration_score(duration_ms, got_duration_ms)
    return 3.0 * t + 1.5 * a + 1.0 * d


# ---- QRC 解析（QQ音乐逐字） ----

_QRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")
_QRC_WORD = re.compile(r"\((\d+),(\d+)\)")

# 纯元数据行（[ti:] [ar:] [offset:] 等）不生成歌词行
_QRC_META = re.compile(r"^\[[a-zA-Z#]+:")


def parse_qrc(qrc_text):
    """解析 QRC 为 [LyricLine]。

    语法：[行起始ms,行时长ms]字(绝对起始ms,时长ms)字(绝对起始ms,时长ms)…
    单词时间戳跟在文字后面（绝对毫秒）；[ti:] 等元数据行跳过。
    """
    lines = []
    for raw in (qrc_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _QRC_LINE.match(line)
        if not m:
            continue
        start_ms = int(m.group(1))
        end_ms = start_ms + int(m.group(2))
        body = line[m.end():]

        words = []
        pos = 0
        for wm in _QRC_WORD.finditer(body):
            seg = body[pos:wm.start()]
            if seg:
                ws, wd = int(wm.group(1)), int(wm.group(2))
                words.append(LyricWord(ws, ws + wd, seg))
            pos = wm.end()
        tail = body[pos:]
        if tail and words:
            words[-1].text += tail  # 尾部散字（通常是无时间戳的空格）并入末词

        text = re.sub(r"\(\d+,\d+\)", "", body)
        if not text.strip():
            continue  # 间奏占位行
        lines.append(LyricLine(start_ms, end_ms, text.strip(), words))
    return lines


# ---- KRC 解析（酷狗逐字） ----

_KRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")
_KRC_WORD = re.compile(r"<(\d+),(\d+),\d+>")
_KRC_LANGUAGE = re.compile(r"^\[language:([A-Za-z0-9+/=]+)\]")
_KRC_META = re.compile(r"^\[[a-zA-Z#]+:")

_KRC_KEY = bytes([0x40, 0x47, 0x61, 0x77, 0x5E, 0x32, 0x74, 0x47,
                  0x51, 0x36, 0x31, 0x2D, 0xCE, 0xD2, 0x6E, 0x69])


def decrypt_krc(b64_content):
    """base64 → 去 krc1 魔数 → XOR → zlib → UTF-8 文本。失败抛异常。"""
    raw = base64.b64decode(b64_content)
    if raw[:4] != b"krc1":
        raise ValueError("not a krc1 payload")
    body = raw[4:]
    dec = bytes(b ^ _KRC_KEY[i % len(_KRC_KEY)] for i, b in enumerate(body))
    return zlib.decompress(dec).decode("utf-8", errors="replace")


def parse_krc(krc_text):
    """解析 KRC 为 [LyricLine]。

    语法：[行起始ms,行时长ms]<相对偏移ms,时长ms,0>字<偏移,时长,0>字…
    单词时间戳在文字前面（相对行首偏移）；[language:base64json] 内
    type=1 是按行索引对齐的逐行翻译。
    """
    lines = []
    translations = []
    for raw in (krc_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lm = _KRC_LANGUAGE.match(line)
        if lm:
            try:
                payload = json.loads(base64.b64decode(lm.group(1)))
                for item in payload.get("content") or []:
                    if item.get("type") == 1:
                        rows = item.get("lyricContent") or []
                        translations = [(r[0] if r else "").strip() for r in rows]
            except Exception:
                pass
            continue
        m = _KRC_LINE.match(line)
        if not m:
            continue  # [id:] [total:] 等元数据
        start_ms = int(m.group(1))
        end_ms = start_ms + int(m.group(2))
        body = line[m.end():]

        words = []
        pos = 0
        pending = None  # 上一个时间戳的 (offset, dur)，其文字在时间戳之后
        for wm in _KRC_WORD.finditer(body):
            seg = body[pos:wm.start()]
            if pending is not None and seg:
                off, dur = pending
                words.append(LyricWord(start_ms + off, start_ms + off + dur, seg))
            pending = (int(wm.group(1)), int(wm.group(2)))
            pos = wm.end()
        tail = body[pos:]
        if pending is not None and tail:
            off, dur = pending
            words.append(LyricWord(start_ms + off, start_ms + off + dur, tail))

        text = re.sub(r"<\d+,\d+,\d+>", "", body).strip()
        if not text:
            continue  # 间奏占位
        lines.append(LyricLine(start_ms, end_ms, text, words))

    # 翻译按行索引对齐（酷狗的 translation 行与歌词行一一对应）
    if translations:
        for i, ln in enumerate(lines):
            if i < len(translations) and translations[i]:
                ln.translation = translations[i]
    return lines


# ---- 翻译按时间对齐（QQ 明文 LRC 翻译 / 网易云 tlyric 共用） ----

def apply_lrc_translation(lines, trans_entries):
    """把 [(time_ms, text)] 翻译按时间戳贴到原文行上（沿用网易云的容差对齐）。"""
    if not lines or not trans_entries:
        return
    used = [False] * len(trans_entries)
    for ln in lines:
        if ln.translation or netease_lyrics._CREDIT_START.match(ln.text):
            continue
        best_i, best_d = -1, 201
        for i, (tt, _) in enumerate(trans_entries):
            if used[i]:
                continue
            d = abs(tt - ln.start_ms)
            if d < best_d:
                best_d, best_i = d, i
        if best_i >= 0:
            used[best_i] = True
            ln.translation = trans_entries[best_i][1]


# ---- Provider：QQ音乐 ----

class QqMusicProvider:
    source_id = "qqmusic"

    def search(self, title, artist, duration_ms):
        """搜索并返回 (best_song_dict, score) 或 (None, 0)。"""
        query = f"{title} {artist}".strip() or title
        body = json.dumps({
            "music.search.SearchCgiService": {
                "method": "DoSearchForQQMusicDesktop",
                "module": "music.search.SearchCgiService",
                "param": {"num_per_page": 20, "page_num": 1, "query": query, "search_type": 0},
            }
        }).encode()
        data = _http_json(
            "https://u.y.qq.com/cgi-bin/musicu.fcg", data=body,
            headers={"Referer": "https://y.qq.com/", "Origin": "https://y.qq.com",
                     "Content-Type": "application/json"})
        songs = ((data.get("music.search.SearchCgiService") or {}).get("data") or {}) \
            .get("body", {}).get("song", {}).get("list", []) or []
        best, best_score = None, 0.0
        for s in songs:
            got_artist = "、".join(x.get("name", "") for x in (s.get("singer") or []))
            sc = _score_candidate(
                title, artist, s.get("name") or s.get("title") or "",
                got_artist, duration_ms, (s.get("interval") or 0) * 1000)
            if sc > best_score:
                best, best_score = s, sc
        return best, best_score

    def fetch(self, song):
        """抓取 QRC 原文（hex 解密）+ 明文 LRC 翻译，返回 LyricsDocument 或 None。"""
        import qq_des

        music_id = song.get("id")
        if not music_id:
            return None
        url = ("https://c.y.qq.com/qqmusic/fcgi-bin/lyric_download.fcg"
               f"?version=15&miniversion=82&lrctype=4&musicid={music_id}")
        text = _http_text(url, headers={"Referer": "https://y.qq.com/"})

        import re as _re
        cdatas = [c.strip() for c in _re.findall(r"<!\[CDATA\[(.*?)\]\]>", text, _re.S)]
        original_qrc = ""
        for c in cdatas:
            if c and _re.fullmatch(r"[0-9a-fA-F]+", c) and len(c) >= 64:
                try:
                    decrypted = qq_des.decrypt_qrc_payload(c)
                    # 载荷本身是 XML：Lyric_1 LyricContent="…QRC 原文…"
                    m = _re.search(r'<Lyric_1[^>]*LyricContent="([^"]*)"', decrypted, _re.S)
                    if m:
                        original_qrc = m.group(1)
                        break
                except Exception:
                    continue

        lines = parse_qrc(original_qrc)
        if not lines:
            return None

        # CDATA 中第一段非 hex 的明文 LRC 是翻译（hex 段是加密的原文/罗马音）
        translation_lrc = ""
        for c in cdatas:
            if not c or _re.fullmatch(r"[0-9a-fA-F]+", c):
                continue
            if _re.search(r"^\[\d{1,3}:\d{1,2}[.:]", c, _re.M):
                translation_lrc = c
                break
        if translation_lrc:
            trans_entries = [e for e in netease_lyrics.parse_lrc(translation_lrc) if e[1].strip()]
            apply_lrc_translation(lines, trans_entries)

        name = song.get("name") or song.get("title") or ""
        return LyricsDocument(lines, self.source_id, name)


# ---- Provider：酷狗音乐 ----

class KugouProvider:
    source_id = "kugou"

    def search(self, title, artist, duration_ms):
        """两段式：song_search_v2 找歌（拿 hash），lyrics search 找歌词候选。"""
        query = f"{title} {artist}".strip() or title
        params = urllib.parse.urlencode({"keyword": query, "page": 1, "pagesize": 20})
        data = _http_json(f"https://songsearch.kugou.com/song_search_v2?{params}")
        lists = (data.get("data") or {}).get("lists") or []

        best, best_score = None, 0.0
        for s in lists:
            got_title = s.get("SongName") or s.get("songname") or ""
            got_artist = s.get("SingerName") or s.get("singername") or ""
            got_ms = int(s.get("Duration") or s.get("duration") or 0) * 1000
            sc = _score_candidate(title, artist, got_title, got_artist, duration_ms, got_ms)
            if sc > best_score:
                best, best_score = s, sc
        if best is None or best_score < _ACCEPT:
            return None, best_score
        return best, best_score

    def fetch(self, song):
        """lyrics search → download krc → 解密解析（翻译在 [language:] 内）。"""
        keyword = f"{song.get('SingerName', '')} - {song.get('SongName', '')}".strip(" -")
        params = urllib.parse.urlencode({
            "ver": 1, "man": "yes", "client": "pc", "keyword": keyword,
            "duration": int(song.get("Duration") or 0) * 1000,
            "hash": song.get("FileHash") or song.get("hash") or "",
        })
        data = _http_json(f"https://lyrics.kugou.com/search?{params}")
        cands = data.get("candidates") or []
        if not cands:
            return None
        cand = cands[0]
        params = urllib.parse.urlencode({
            "ver": 1, "client": "pc", "id": cand.get("id"),
            "accesskey": cand.get("accesskey"), "fmt": "krc", "charset": "utf8",
        })
        data = _http_json(f"https://lyrics.kugou.com/download?{params}")
        content = data.get("content")
        if not content:
            return None
        krc_text = decrypt_krc(content)
        lines = parse_krc(krc_text)
        if not lines:
            return None
        return LyricsDocument(lines, self.source_id, song.get("SongName") or "")


# ---- Provider：网易云音乐（复用 netease_lyrics） ----

class NeteaseProvider:
    source_id = "netease"

    def search(self, title, artist, duration_ms):
        queries = []
        if title and artist:
            queries.append(f"{title} {artist}")
        if title:
            queries.append(title)
        best_song, best_score = None, 0.0
        for q in queries:
            songs = netease_lyrics.search_songs(q)
            for s in songs:
                sc = netease_lyrics.score_song(s, title, artist, duration_ms)
                if sc > best_score:
                    best_song, best_score = s, sc
            if best_score >= netease_lyrics._STRONG_SCORE:
                break
        return best_song, best_score

    def fetch(self, song):
        lrc, tlrc = netease_lyrics.fetch_lyrics(song["id"])
        entries = netease_lyrics.parse_lrc(lrc)
        if not entries:
            return None
        trans = netease_lyrics.parse_lrc(tlrc) if tlrc else []
        aligned = netease_lyrics.align_translation(entries, trans)
        lines = []
        for t, text, tr in aligned:
            end = None  # 行级歌词用下一行起始作为行结束（渲染时回填）
            lines.append(LyricLine(t, end, text, [], tr))
        # 行结束时间回填
        for i, ln in enumerate(lines):
            if ln.end_ms is None:
                ln.end_ms = lines[i + 1].start_ms if i + 1 < len(lines) else ln.start_ms + 5000
        return LyricsDocument(lines, self.source_id, song.get("name", ""))


_PROVIDERS = {
    "qqmusic": QqMusicProvider,
    "kugou": KugouProvider,
    "netease": NeteaseProvider,
}


def get_provider(source_id):
    cls = _PROVIDERS.get(source_id)
    return cls() if cls else None


def fetch_document(title, artist, duration_ms, source="auto"):
    """按歌词源抓取歌词文档。

    source: "auto"（按 QQ → 酷狗 → 网易云顺序取第一个匹配）或具体源 id。
    返回 (LyricsDocument | None, source_id | None)；网络错误向上抛出。
    """
    order = AUTO_ORDER if source == "auto" else (source,)
    last_err = None
    for sid in order:
        provider = get_provider(sid)
        if provider is None:
            continue
        try:
            song, score = provider.search(title, artist, duration_ms)
            if song is None or score < _ACCEPT:
                continue
            doc = provider.fetch(song)
            if doc is not None and doc.lines:
                return doc, sid
        except Exception as e:
            last_err = e
            continue  # 单源失败继续尝试下一个源
    if last_err is not None:
        raise last_err
    return None, None
