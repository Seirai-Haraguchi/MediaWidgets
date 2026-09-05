"""端到端实测：三个歌词源完整链路（需要网络）。"""
import lyrics_providers as lp

CASES = [
    ("Lemon", "米津玄師", 259000),   # 日文 + 翻译
    ("晴天", "周杰伦", 269000),      # 中文
    ("アイドル", "YOASOBI", 213000), # 日文新歌
]

for title, artist, dur in CASES:
    print("=" * 50)
    print(f"{title} / {artist} ({dur}ms)")
    for source in ("auto",):
        doc, used = lp.fetch_document(title, artist, dur, source)
        if doc is None:
            print(f"  [{source}] NO LYRICS")
            continue
        n_trans = sum(1 for l in doc.lines if l.translation)
        n_word = sum(1 for l in doc.lines if l.words)
        print(f"  [{source}] source={used} lines={len(doc.lines)} "
              f"word_lines={n_word} trans_lines={n_trans}")
        for ln in doc.lines[3:6]:
            words_desc = " ".join(f"{w.text}@{w.start_ms}-{w.end_ms}" for w in ln.words[:4])
            print(f"    [{ln.start_ms}-{ln.end_ms}] {ln.text[:28]!r}")
            if words_desc:
                print(f"      words: {words_desc}")
            if ln.translation:
                print(f"      trans: {ln.translation[:30]!r}")
        break
