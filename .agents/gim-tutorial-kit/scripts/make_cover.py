# -*- coding: utf-8 -*-
"""生成 B 站封面（1920×1200，16:10，与视频同一套配色）。

用法: python make_cover.py
输出: ../封面-线路GIM拆解.png

复用要点（换一集只改这几处）：
  1. 眉标      '从零开始学国网 GIM 标准' + tag 'EP 01 · 线路篇'
  2. 主标题    '一条 .gim 里' / [('到底',FG),('装了',CYAN),('什么',CYAN)]
  3. 副线      '784 字节头 · 五级层级 · 六种格式 · 三种指针'
  4. 三个数    stats = [('499','个 cbm 文件',CYAN), ...]
  5. 底栏两行  '不用建模软件，只用终端和记事本'
  6. 右侧链条  levels 里的层级名与数量
  7. 终端窗    lines 里的几行示例

坑：含汉字的字符串必须用 msyhbd，Consolas 会渲染成豆腐块。
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '封面-线路GIM拆解.png')

W, H = 1920, 1200
BG = (15, 23, 42)
PANEL2 = (23, 33, 54)
BORDER = (51, 65, 85)
BLUE = (37, 99, 235)
CYAN = (34, 211, 238)
AMBER = (245, 158, 11)
GREEN = (34, 197, 94)
FG = (226, 232, 240)
MUTED = (148, 163, 184)


def F(kind, size):
    paths = {
        'bold': ['C:/Windows/Fonts/msyhbd.ttc', 'C:/Windows/Fonts/msyh.ttc'],
        'reg': ['C:/Windows/Fonts/msyh.ttc'],
        'mono': ['C:/Windows/Fonts/consolab.ttf', 'C:/Windows/Fonts/consola.ttf'],
    }[kind]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


img = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(img)

# ---- 背景：左上角一圈冷光，右下角一圈暖光 ----
for r in range(900, 0, -12):
    a = (1 - r / 900) ** 2 * 0.10
    c = tuple(int(BG[i] + (BLUE[i] - BG[i]) * a) for i in range(3))
    d.ellipse([260 - r, 120 - r, 260 + r, 120 + r], fill=c)
for r in range(760, 0, -12):
    a = (1 - r / 760) ** 2 * 0.07
    c = tuple(int(BG[i] + (AMBER[i] - BG[i]) * a) for i in range(3))
    d.ellipse([1820 - r, 1120 - r, 1820 + r, 1120 + r], fill=c)

LX = 108

# ---- 眉标 ----
d.rectangle([LX, 128, LX + 8, 176], fill=AMBER)
d.text((LX + 30, 130), '从零开始学国网 GIM 标准', font=F('bold', 34), fill=AMBER)
tag = 'EP 01 · 线路篇'
tw = d.textlength(tag, font=F('bold', 26))
d.rounded_rectangle([LX + 30 + d.textlength('从零开始学国网 GIM 标准', font=F('bold', 34)) + 24,
                     132, LX + 30 + d.textlength('从零开始学国网 GIM 标准', font=F('bold', 34)) + 24 + tw + 32, 176],
                    22, outline=(90, 105, 130), width=2)
d.text((LX + 30 + d.textlength('从零开始学国网 GIM 标准', font=F('bold', 34)) + 44, 138),
       tag, font=F('bold', 26), fill=MUTED)

# ---- 主标题 ----
d.text((LX, 232), '一条 .gim 里', font=F('bold', 104), fill=FG)
x = LX
for seg, col in [('到底', FG), ('装了', CYAN), ('什么', CYAN)]:
    d.text((x, 360), seg, font=F('bold', 104), fill=col)
    x += d.textlength(seg, font=F('bold', 104))

# ---- 副线 ----
d.rectangle([LX, 528, LX + 120, 532], fill=CYAN)
d.text((LX, 562), '784 字节头 · 五级层级 · 六种格式 · 三种指针',
       font=F('reg', 40), fill=MUTED)

# ---- 三个数字 ----
stats = [('499', '个 cbm 文件', CYAN), ('779', '条引用边', AMBER), ('343', '个部件', GREEN)]
sx = LX
for i, (n, lab, col) in enumerate(stats):
    d.text((sx, 674), n, font=F('mono', 88), fill=col)
    d.text((sx, 784), lab, font=F('reg', 26), fill=MUTED)
    sx += 340

# ---- 底栏 ----
d.rectangle([LX, 940, LX + 940, 944], fill=(45, 58, 80))
d.text((LX, 978), '不用建模软件，只用终端和记事本', font=F('bold', 34), fill=FG)
d.text((LX, 1038), '真实线路交付件 · 逐字节拆到一根绝缘子串',
       font=F('reg', 28), fill=MUTED)

# ---- 右侧：五级链条 ----
RX, RW = 1180, 596
d.text((RX, 128), '五级链条', font=F('bold', 40), fill=CYAN)
d.rectangle([RX, 186, RX + 92, 190], fill=CYAN)

levels = [('F1', '工程', '× 1', 1),
          ('F2', '分段', '× 2', 2),
          ('F3', '耐张段', '× 4', 3),
          ('F4', '设备组', '× 148', 4),
          ('L5', '部件', '× 343', 5)]
y0, step, ch = 216, 108, 84
cols = [CYAN, CYAN, (56, 189, 248), AMBER, AMBER]
for i, (lv, nm, cnt, _) in enumerate(levels):
    y = y0 + i * step
    col = cols[i]
    d.rounded_rectangle([RX, y, RX + RW, y + ch], 10, fill=PANEL2, outline=BORDER, width=2)
    d.rectangle([RX, y + 8, RX + 6, y + ch - 8], fill=col)
    d.text((RX + 28, y + 12), lv, font=F('mono', 24), fill=col)
    d.text((RX + 28, y + 42), nm, font=F('bold', 38), fill=FG)
    cw = d.textlength(cnt, font=F('mono', 34))
    d.text((RX + RW - cw - 28, y + 28), cnt, font=F('mono', 34), fill=col)
    if i < 4:                                    # 竖线
        d.rectangle([RX + 46, y + ch, RX + 49, y + step], fill=(71, 85, 105))

# ---- 右下：终端小窗 ----
TY = 812
d.rounded_rectangle([RX, TY, RX + RW, TY + 300], 12, fill=(13, 17, 23), outline=BORDER, width=2)
d.rounded_rectangle([RX, TY, RX + RW, TY + 40], 12, fill=(23, 30, 44))
d.rectangle([RX, TY + 28, RX + RW, TY + 40], fill=(23, 30, 44))
for i, c in enumerate([(248, 113, 113), (251, 191, 36), (52, 211, 153)]):
    d.ellipse([RX + 18 + i * 20, TY + 14, RX + 30 + i * 20, TY + 26], fill=c)
d.text((RX + 88, TY + 8), 'Cbm / project.cbm', font=F('mono', 20), fill=MUTED)

lines = [('SUBSYSTEM=7f9e…cbm', CYAN),
         ('→ ENTITYNAME=F1System', FG),
         ('→ SECTIONS.NUM=2', FG),
         ('→ GROUP0=f3a5…cbm', AMBER)]
for i, (s, c) in enumerate(lines):
    d.text((RX + 26, TY + 62 + i * 46), s, font=F('mono', 24), fill=c)

img.save(OUT)
print('saved', OUT, img.size)
