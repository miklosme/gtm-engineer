"""Transcribe + diarize one 16 kHz mono wav into word-level JSON: {"words": [{s, e, w, spk}]}.

Usage: transcribe.py <in.wav> <out.json>
ASR: faster-whisper large-v3 on CUDA. Speakers: ECAPA embeddings on 1.5 s sliding windows,
agglomerative clustering (cosine threshold THR env, default 0.75), tiny clusters merged.
"""
import json, os, sys
import numpy as np, soundfile as sf, torch
from faster_whisper import WhisperModel
from speechbrain.inference.speaker import EncoderClassifier
from sklearn.cluster import AgglomerativeClustering

wav_path, out_path = sys.argv[1], sys.argv[2]
audio, sr = sf.read(wav_path, dtype="float32")
assert sr == 16000, "expected 16 kHz mono wav"

# 1. Speech to text with word timestamps
model = WhisperModel("large-v3", device="cuda", compute_type="float16")
segs, _ = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=True, beam_size=5,
                           condition_on_previous_text=False)
words = [{"s": w.start, "e": w.end, "w": w.word} for s in segs for w in s.words]
del model
torch.cuda.empty_cache()

# 2. Speaker embeddings on sliding windows over speech.
# cuDNN off: the pip cuDNN that ctranslate2 needs clashes with torch's own.
torch.backends.cudnn.enabled = False
enc = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cuda"},
                                     savedir=os.path.expanduser("~/.cache/sb-ecapa"))
WIN, HOP = 1.5, 0.5
total = len(audio) / sr
speech = np.zeros(int(total / HOP) + 2, bool)
for w in words:
    speech[int(w["s"] / HOP):int(w["e"] / HOP) + 1] = True
starts = [i * HOP for i in range(len(speech)) if speech[i] and i * HOP + WIN <= total]
if len(starts) < 2:
    for w in words:
        w["spk"] = 1
    json.dump({"words": words}, open(out_path, "w"))
    sys.exit(0)
embs = []
for b in range(0, len(starts), 128):
    chunk = np.stack([audio[int(t * sr):int(t * sr) + int(WIN * sr)] for t in starts[b:b + 128]])
    with torch.no_grad():
        embs.append(enc.encode_batch(torch.from_numpy(chunk).cuda()).squeeze(1).cpu().numpy())
embs = np.concatenate(embs)
embs /= np.linalg.norm(embs, axis=1, keepdims=True)

# 3. Cluster; fold clusters under 4% of windows into the nearest big one
lab = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                              distance_threshold=float(os.environ.get("THR", "0.75"))).fit_predict(embs)
counts = np.bincount(lab)
big = [c for c in range(len(counts)) if counts[c] >= 0.04 * len(lab)] or [int(counts.argmax())]
cent = {c: embs[lab == c].mean(0) for c in big}
for i, l in enumerate(lab):
    if l not in cent:
        lab[i] = max(big, key=lambda c: embs[i] @ cent[c])
sm = np.array([np.bincount(lab[max(0, i - 2):i + 3]).argmax() for i in range(len(lab))])
order = {}
for l in sm:
    order.setdefault(int(l), len(order) + 1)
win_t = np.array(starts) + WIN / 2

# 4. Each word takes the speaker of the nearest window
for w in words:
    w["spk"] = order[int(sm[int(np.abs(win_t - (w["s"] + w["e"]) / 2).argmin())])]
json.dump({"words": words}, open(out_path, "w"))
