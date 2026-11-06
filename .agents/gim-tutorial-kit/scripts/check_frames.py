# -*- coding: utf-8 -*-
"""抽静帧检查版式。

用法（在本目录，也就是 make_video.py 所在处执行）：

    python check_frames.py                 # 全部段，每段 4 帧
    python check_frames.py 3,7,12          # 只查第 3、7、12 段
    python check_frames.py 9 --real        # 用真实配音时长（要联网生成 mp3）
    python check_frames.py 9 --real --at 0.2,0.6,0.95

输出到 _video_work/chk/sNN_k.png。

只看四件事：重叠、裁切、超界、空页。
"""
import argparse
import importlib.util
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, 'make_video.py')

spec = importlib.util.spec_from_file_location('mv', TARGET)
mv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mv)

ap = argparse.ArgumentParser()
ap.add_argument('segs', nargs='?', default='', help='段号，逗号分隔，如 3,7,12；空=全部')
ap.add_argument('--real', action='store_true', help='用真实配音时长（需联网）')
ap.add_argument('--dur', type=float, default=12.0, help='--real 关闭时的固定时长')
ap.add_argument('--at', default='0.25,0.55,0.85,0.99', help='段内时间占比')
args = ap.parse_args()

only = [int(x) for x in args.segs.split(',') if x.strip()]
fracs = [float(x) for x in args.at.split(',') if x.strip()]

if args.real:
    durs = [mv.dur_of(mv.tts_get(i)) + mv.TAIL for i in range(len(mv.SEGS))]
else:
    durs = [args.dur] * len(mv.SEGS)
mv.DURS = durs                       # chrome() 画时间轴要用

out_dir = os.path.join(HERE, '_video_work', 'chk')
os.makedirs(out_dir, exist_ok=True)

for i, seg in enumerate(mv.SEGS):
    if only and (i + 1) not in only:
        continue
    dur = durs[i]
    for k, frac in enumerate(fracs):
        t = frac * dur
        img = Image.new('RGB', (mv.W, mv.H), mv.BG)
        if getattr(mv, 'CUR_IMG', None):
            mv.CUR_IMG[0] = img      # 有贴图的段要用
        d = ImageDraw.Draw(img)
        seg['draw'](d, t, dur)
        mv.chrome(d, i, t, dur)
        img.save(os.path.join(out_dir, f's{i + 1:02d}_{k}.png'))
    print(f's{i + 1:02d} {dur:6.1f}s  {seg["title"]}')

print('->', out_dir)
