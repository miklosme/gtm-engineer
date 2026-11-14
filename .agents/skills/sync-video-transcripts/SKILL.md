---
name: sync-video-transcripts
description: Transcribe new videos from a YouTube playlist into Markdown files, one per video, with named speakers.
disable-model-invocation: true
---

Brings a transcripts folder up to date with a YouTube playlist. Scope ends at files in the git workspace: leave every change uncommitted.

**Inputs**: the playlist URL (required; if none was given, ask for it and stop) and the transcripts folder (default `<repo>/videos`). Below, `<url>` and `<dir>` stand for them.

## Steps

1. **Sync.** Run `scripts/sync.sh <url> <dir>` from this skill's folder. It transcribes each playlist video whose watch URL appears in no `<dir>/*.md` header and prints `NEW <path>` per file written.
   - No `NEW` lines: the folder is current. Stop here.
   - Non-zero exit: report the stderr tail and stop. A file is written only once its video is fully transcribed, so the next run retries cleanly.

2. **Name speakers** in every `NEW` file. Replace each `Speaker N`, in the `**Speakers:**` header and in the paragraph labels, with the person's real name. Take names from the video description, introductions, and how people address each other. Clusters that are the same person (a host's intro voiceover or ad read) get the same name. If a name is only inferred, append `(likely)`. If a speaker is never named, use their role (`Host`, `Guest`). Done when `grep -l 'Speaker [0-9]' <dir>/*.md` prints nothing.

3. **Fix turns** in every `NEW` file with more than one speaker. Read the whole transcript. Where content clearly belongs to the other speaker (a question labelled as the guest, an answer continuing the previous speaker's sentence), relabel the paragraph or split it, giving the split-off part the same timestamp. Short backchannels (`Yeah.`, `Exactly.`) stay where they are. Correct misheard person and tool names along the way. Done when every paragraph has been read.

4. **Index.** Run `scripts/sync.sh --index <url> <dir>` to rebuild `<dir>/README.md` from the file headers, titled with the playlist's YouTube title.

## Reference

- **Idempotency key**: the `- **URL:** https://www.youtube.com/watch?v=<id>` line in a transcript header. Existing transcripts are never regenerated or renumbered. A video removed from the playlist keeps its transcript.
- **Numbering**: new files take the next free `NN-` prefix, so a file's number is its order of arrival.
- **Recurring mishearings**: `FIXUPS` in `scripts/render.py` fixes them at render time. When a step 3 fix is a term Whisper is likely to miss again (a tool or person name), add it there as well.
- **Environment**: needs an NVIDIA GPU, `node` (yt-dlp's JS runtime), and `uv` (installed automatically if missing). The Python venv lives in `~/.cache/video-transcripts/venv` and is built on first run. Each run upgrades yt-dlp, which fixes YouTube 403 errors.
- **Speaker clustering**: `THR` (default `0.75`) is the cosine-distance threshold in `scripts/transcribe.py`. Raise it if one person splits into several clusters; lower it if two people merge into one.
