#!/usr/bin/env bash
# Transcribe playlist videos that have no transcript in videos/ yet.
# Prints one line per new file: NEW <path>. Prints nothing new when the workspace is up to date.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PLAYLIST="$(python3 -I "$HERE/render.py" playlist)"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
VIDEOS="$ROOT/videos"
VENV="${XDG_CACHE_HOME:-$HOME/.cache}/gtm-engineer-transcripts/venv"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
PY="$VENV/bin/python"
mkdir -p "$VIDEOS"

if [ ! -x "$PY" ]; then
  [ -x "$UV" ] || pip install --user --break-system-packages -q uv
  "$UV" venv -q -p 3.12 "$VENV"
  "$UV" pip install -q -p "$PY" faster-whisper torch torchaudio speechbrain scikit-learn soundfile \
    nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" "yt-dlp[default]"
fi
# YouTube breaks old yt-dlp releases often; staying current is the fix for 403s.
"$UV" pip install -q -p "$PY" -U "yt-dlp[default]"
YTDLP=("$VENV/bin/yt-dlp" --no-warnings --js-runtimes node)
export LD_LIBRARY_PATH="$("$PY" -c 'import nvidia.cublas as a, nvidia.cudnn as b; print(a.__path__[0]+"/lib:"+b.__path__[0]+"/lib")')"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

ids="$("${YTDLP[@]}" --flat-playlist --print id "$PLAYLIST")"
[ -n "$ids" ] || { echo "playlist listing returned no videos" >&2; exit 1; }
for id in $ids; do
  # Idempotency key: the video's watch URL in a transcript's header.
  grep -qsF "watch?v=$id" "$VIDEOS"/*.md && continue
  echo "transcribing $id" >&2
  "${YTDLP[@]}" -q -f bestaudio -x --audio-format wav --postprocessor-args "ffmpeg:-ac 1 -ar 16000" \
    --write-info-json -o "$WORK/$id.%(ext)s" "https://www.youtube.com/watch?v=$id"
  "$PY" -I "$HERE/transcribe.py" "$WORK/$id.wav" "$WORK/$id.words.json" 2> "$WORK/$id.log" \
    || { tail -20 "$WORK/$id.log" >&2; exit 1; }
  echo "NEW $("$PY" -I "$HERE/render.py" video "$WORK/$id.info.json" "$WORK/$id.words.json" "$VIDEOS")"
  rm -f "$WORK/$id".*
done
