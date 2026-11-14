"""Markdown rendering for video transcripts.

  render.py video <info.json> <words.json> <videos_dir>   write the next NN-slug.md, print its path
  render.py index <videos_dir>                             rebuild videos/README.md from file headers
  render.py playlist                                       print the playlist URL (single source of truth)
"""
import glob, json, os, re, sys

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLEj5JgcDjKAE"

# Recurring Whisper mishearings of GTM tool names. Extend when a new one shows up twice.
FIXUPS = [(r"\b(cloud|claude|slot) ?code\b", "Claude Code"), (r"\bcloud co-?work\b", "Claude Cowork"),
          (r"\bcloud or chat ?gpt\b", "Claude or ChatGPT"), (r"\bchat ?gpt or cloud\b", "ChatGPT or Claude"),
          (r"\bchat gpt\b", "ChatGPT"), (r"\bdeep line\b", "Deepline"), (r"\bsmart lead\b", "Smartlead"),
          (r"\bzoom info\b", "ZoomInfo"), (r"\bNA10\b", "n8n"),
          (r"\bsignal-based code market\b", "signal-based go-to-market"),
          (r"\bjai tour\b", "Jai Toor"), (r"\btim jakobsen\b", "Tim Yakubson")]
SENT_END = r"[.?!]$"


def fixup(s):
    for a, b in FIXUPS:
        s = re.sub(a, b, s, flags=re.I)
    return s


def ts(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:70].rstrip("-")


def clean_runs(words):
    """Absorb sub-second speaker flicker; snap speaker changes to the nearest sentence end."""
    runs = []
    for i, w in enumerate(words):
        if runs and runs[-1][0] == w["spk"]:
            runs[-1][2] = i
        else:
            runs.append([w["spk"], i, i])
    k = 1
    while k < len(runs) - 1:
        sp, a, b = runs[k]
        if runs[k - 1][0] == runs[k + 1][0] != sp and words[b]["e"] - words[a]["s"] < 1.0 and b - a < 3:
            for i in range(a, b + 1):
                words[i]["spk"] = runs[k - 1][0]
            runs[k - 1][2] = runs[k + 1][2]
            del runs[k:k + 2]
            k = max(1, k - 1)
        else:
            k += 1
    for i in range(1, len(words)):
        if words[i]["spk"] == words[i - 1]["spk"] or re.search(SENT_END, words[i - 1]["w"].strip()):
            continue
        best = next((j for d in range(1, 5) for j in (i - d, i + d)
                     if 0 < j < len(words) and re.search(SENT_END, words[j - 1]["w"].strip())), None)
        if best:
            new, old = words[i]["spk"], words[i - 1]["spk"]
            lo, hi = sorted((i, best))
            for k in range(lo, hi):
                words[k]["spk"] = new if best < i else old
    return words


def paragraphs(words, multi):
    """Yield [speaker, start, text]: break on speaker change, long pause, or ~110 words."""
    cur, start, spk = [], None, None
    for i, w in enumerate(words):
        sent_end = cur and re.search(SENT_END, cur[-1]["w"].strip())
        if cur and ((multi and w["spk"] != spk) or (len(cur) > 110 and sent_end)
                    or (sent_end and w["s"] - words[i - 1]["e"] > 2.0)):
            yield [spk, start, "".join(x["w"] for x in cur).strip()]
            cur = []
        if not cur:
            start, spk = w["s"], w["spk"]
        cur.append(w)
    if cur:
        yield [spk, start, "".join(x["w"] for x in cur).strip()]


def render_video(info_path, words_path, dest):
    info, words = json.load(open(info_path)), clean_runs(json.load(open(words_path))["words"])
    multi = len({w["spk"] for w in words}) > 1
    paras = []
    for p in paragraphs(words, multi):  # merge fragments under 8 words into a same-speaker neighbour
        if paras and paras[-1][0] == p[0] and min(len(p[2].split()), len(paras[-1][2].split())) < 8:
            paras[-1][2] += " " + p[2]
        else:
            paras.append(p)
    used = list(dict.fromkeys(p[0] for p in paras))
    date = info.get("upload_date") or ""
    out = [f"# {info['title']}", "",
           f"- **Channel:** {info.get('channel') or info.get('uploader') or ''}",
           f"- **URL:** https://www.youtube.com/watch?v={info['id']}",
           f"- **Published:** {date[:4]}-{date[4:6]}-{date[6:]}" if date else "- **Published:**",
           f"- **Duration:** {ts(info['duration'])}",
           f"- **Speakers:** {', '.join(f'Speaker {s}' for s in used)}", ""]
    desc = (info.get("description") or "").strip()
    if desc:
        out += ["<details><summary>Video description</summary>", "", desc, "", "</details>", ""]
    out += ["## Transcript", ""]
    chapters, ch = info.get("chapters") or [], 0
    for spk, start, text in paras:
        while ch < len(chapters) and chapters[ch]["start_time"] <= start + 1:
            out += [f"### {chapters[ch]['title']} ({ts(chapters[ch]['start_time'])})", ""]
            ch += 1
        out += [f"[{ts(start)}] {f'**Speaker {spk}:** ' if multi else ''}{fixup(text)}", ""]
    nums = [int(m.group(1)) for f in os.listdir(dest) if (m := re.match(r"(\d+)-", f))]
    path = os.path.join(dest, f"{max(nums, default=0) + 1:02d}-{slug(info['title'])}.md")
    tmp = path + ".tmp"
    open(tmp, "w").write("\n".join(out).rstrip() + "\n")
    os.replace(tmp, path)
    print(path)


def rebuild_index(dest):
    esc = lambda s: s.replace("|", "\\|")
    rows = []
    for f in sorted(glob.glob(os.path.join(dest, "[0-9]*-*.md"))):
        head = open(f).read().split("## Transcript")[0]
        field = lambda k: (re.search(rf"^- \*\*{k}:\*\* ?(.*)$", head, re.M) or [None, ""])[1]
        title = head.splitlines()[0].removeprefix("# ")
        n = int(os.path.basename(f).split("-")[0])
        rows.append(f"| {n} | [{esc(title)}]({os.path.basename(f)}) | {esc(field('Channel'))} | "
                    f"{field('Duration')} | {esc(field('Speakers'))} |")
    open(os.path.join(dest, "README.md"), "w").write(
        f"# Video transcripts\n\nTranscripts of the videos in the [GTM engineer playlist]({PLAYLIST_URL}).\n\n"
        "Generated locally: audio via yt-dlp, speech-to-text with Whisper large-v3 (faster-whisper), "
        "speaker separation via ECAPA voice embeddings + clustering. Expect occasional misheard names/tools and "
        "speaker mislabels around quick back-and-forth exchanges.\n\n"
        "| # | Video | Channel | Length | Speakers |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "video":
        render_video(*sys.argv[2:5])
    elif sys.argv[1] == "index":
        rebuild_index(sys.argv[2])
    else:
        print(PLAYLIST_URL)
