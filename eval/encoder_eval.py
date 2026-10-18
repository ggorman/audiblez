"""Compare AAC encoders for audiblez TTS output (24 kHz mono speech).

usage: python encoder_eval.py CORPUS_DIR OUT_DIR FDK_FFMPEG
Needs: numpy soundfile scipy pesq pystoi; system `ffmpeg` with aac, aac_at, libopus.
Every candidate is decoded by the system ffmpeg at 24 kHz, aligned to the source,
resampled to 16 kHz and scored with PESQ-WB and STOI.
"""
import csv
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile
from pesq import pesq
from pystoi import stoi
from scipy.signal import correlate, resample_poly, stft

SYS = 'ffmpeg'


def candidates(fdk):
    single = lambda ff, *a: [[ff, '-c:a', *a]]
    return {
        # today's core.py: concat step libfdk_aac 192k, then create_m4b re-encodes with native aac 64k
        'current': [[fdk, '-c:a', 'libfdk_aac', '-b:a', '192k'], [fdk, '-c:a', 'aac', '-b:a', '64k']],
        'native64': single(SYS, 'aac', '-b:a', '64k'),
        'native80': single(SYS, 'aac', '-b:a', '80k'),
        'native96': single(SYS, 'aac', '-b:a', '96k'),
        'at64': single(SYS, 'aac_at', '-b:a', '64k', '-aac_at_mode', 'cvbr'),
        'at48': single(SYS, 'aac_at', '-b:a', '48k', '-aac_at_mode', 'cvbr'),
        'at_he32': single(SYS, 'aac_at', '-profile:a', '4', '-b:a', '32k'),  # aac_at takes the numeric profile (4 = HE-AAC)
        'at_he48': single(SYS, 'aac_at', '-profile:a', '4', '-b:a', '48k'),
        'fdk64': single(fdk, 'libfdk_aac', '-b:a', '64k'),
        'fdk48': single(fdk, 'libfdk_aac', '-b:a', '48k'),
        'fdk_he32': single(fdk, 'libfdk_aac', '-profile:a', 'aac_he', '-b:a', '32k'),
        'opus32': single(SYS, 'libopus', '-b:a', '32k'),
    }


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip().splitlines()[-1])


def encode(src, out_dir, cid, stages):
    cur, t0 = src, time.perf_counter()
    for k, (ff, *args) in enumerate(stages):
        dst = out_dir / f'{src.stem}.{cid}.{k}.m4a'
        run([ff, '-y', '-v', 'error', '-i', str(cur), *args, '-f', 'mp4', str(dst)])
        cur = dst
    return cur, time.perf_counter() - t0


def decode(path):
    wav = path.with_suffix('.dec.wav')
    run([SYS, '-y', '-v', 'error', '-i', str(path), '-ar', '24000', '-ac', '1', str(wav)])
    x, _ = soundfile.read(wav, dtype='float64')
    return x


def align(ref, deg, max_lag=4800):
    """Shift deg so it best matches ref (lag found by cross-correlation on the first 10 s)."""
    n = min(len(ref), len(deg), 240000)
    c = correlate(deg[:n], ref[:n], mode='full', method='fft')
    mid = n - 1
    lag = int(np.argmax(c[mid - max_lag:mid + max_lag + 1])) - max_lag
    deg = deg[lag:] if lag >= 0 else np.concatenate([np.zeros(-lag), deg])
    m = min(len(ref), len(deg))
    return ref[:m], deg[:m], lag


def hiband_lsd(ref, deg, sr=24000, lo=8000, hi=12000):
    """RMS log-spectral distance (dB) over lo..hi Hz on speech-active frames; PESQ-WB/STOI can't see > 8 kHz."""
    f, _, R = stft(ref, sr, nperseg=1024)
    _, _, D = stft(deg, sr, nperseg=1024)
    band = (f >= lo) & (f <= hi)
    pr, pd = np.abs(R) ** 2, np.abs(D) ** 2
    active = pr.sum(0) > 1e-3 * pr.sum(0).max()
    eps = 1e-12
    diff = 10 * np.log10(pr[band][:, active] + eps) - 10 * np.log10(pd[band][:, active] + eps)
    return float(np.sqrt((diff ** 2).mean(0)).mean())


def main(corpus, out_dir, fdk):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for src in sorted(corpus.glob('*.wav')):
        ref24, sr = soundfile.read(src, dtype='float64')
        assert sr == 24000 and ref24.ndim == 1, src
        for cid, stages in candidates(fdk).items():
            try:
                enc, secs = encode(src, out_dir, cid, stages)
            except RuntimeError as e:
                rows.append(dict(file=src.stem[:24], cand=cid, error=str(e)))
                continue
            deg24 = decode(enc)
            r, d, lag = align(ref24, deg24)
            r16, d16 = resample_poly(r, 2, 3), resample_poly(d, 2, 3)
            dur = len(ref24) / 24000
            rows.append(dict(
                file=src.stem[:24], cand=cid,
                pesq_wb=pesq(16000, r16, d16, 'wb'), stoi=stoi(r16, d16, 16000), hi_lsd_db=hiband_lsd(r, d),
                bytes=enc.stat().st_size, dur_s=dur,
                kbps=enc.stat().st_size * 8 / dur / 1000, enc_s=secs,
                lag_samples=lag, dur_diff_ms=(len(deg24) - len(ref24)) / 24,
            ))
            print(rows[-1], flush=True)

    keys = ['file', 'cand', 'pesq_wb', 'stoi', 'hi_lsd_db', 'bytes', 'dur_s', 'kbps', 'enc_s', 'lag_samples', 'dur_diff_ms', 'error']
    with open(out_dir / 'results.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if 'error' not in r]
    by = lambda c, k: np.array([r[k] for r in ok if r['cand'] == c])
    lines = ['| cand | PESQ-WB mean | PESQ-WB min | STOI mean | 8-12 kHz LSD dB | kb/s (corpus) | max abs dur diff ms | max abs lag |',
             '|---|---|---|---|---|---|---|---|']
    for c in candidates(fdk):
        p = by(c, 'pesq_wb')
        if not len(p):
            continue
        kbps = by(c, 'bytes').sum() * 8 / by(c, 'dur_s').sum() / 1000  # duration-weighted, includes container overhead
        lines.append(f'| {c} | {p.mean():.3f} | {p.min():.3f} | {by(c, "stoi").mean():.4f} | {by(c, "hi_lsd_db").mean():.2f} | {kbps:.1f} '
                     f'| {np.abs(by(c, "dur_diff_ms")).max():.1f} | {np.abs(by(c, "lag_samples")).max()} |')
    errs = [f'- {r["cand"]} on {r["file"]}: {r["error"]}' for r in rows if 'error' in r]
    (out_dir / 'summary.md').write_text('\n'.join(lines + ([''] + ['Errors:'] + errs if errs else [])) + '\n')
    print('\n'.join(lines + errs))

    # Distinct configs must not give fp64-identical scores (config collapse), and starts must stay
    # sample-aligned (a start offset shifts chapter marks; tail padding after the last chapter is harmless).
    # Hard gate on the AAC-LC candidates a fix can choose from; report the rest as disqualifying warnings.
    names = [c for c in candidates(fdk) if len(by(c, 'pesq_wb'))]
    collapsed = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
                 if np.array_equal(by(a, 'pesq_wb'), by(b, 'pesq_wb'))]
    offset = sorted({(r['cand'], r['lag_samples']) for r in ok if abs(r['lag_samples']) > 1})
    print('WARN config collapse:', collapsed, '\nWARN start offset (samples):', offset)
    lc = {'current', 'native64', 'native80', 'native96', 'at48', 'at64', 'fdk48', 'fdk64'}
    n_files = len(list(corpus.glob('*.wav')))
    missing = {c: n_files - len(by(c, 'pesq_wb')) for c in lc if len(by(c, 'pesq_wb')) != n_files}
    assert not missing, f'LC candidates with failed/missing files: {missing}'
    assert not [p for p in collapsed if lc & set(p)], f'config collapse in LC candidates: {collapsed}'
    assert not [o for o in offset if o[0] in lc], f'LC start offset: {offset}'


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
