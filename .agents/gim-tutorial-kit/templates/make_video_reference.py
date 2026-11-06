# -*- coding: utf-8 -*-
"""
make_video_reference.py —— EP01《线路 GIM 文件拆解》完整渲染实现（参考模板）

产出: 1920×1080 / 20fps / 20 镜 / 14:39
组成: 每段 = 配音(edge-tts，按讲稿 md5 缓存) + PIL 逐帧动画 + ffmpeg 管道编码
分镜: 序 1 + 五章正片 13 + 章封 5 + 实操 1

这是"参考实现"，不是"通用库"。新一集的做法：
  1. 复制本文件为 make_video.py 放在工作目录
  2. 换 SEGS 的 title / narr / ch
  3. 重写需要的 draw_*；可保留 draw_a7（贴截图）、draw_live（终端实录）、chrome（时间轴）
  4. 改 SERIES / EP / TAG

结构导览（搜这些锚点）：
  CONFIG 常量   W/H/FPS/BG/配色/TAIL/MAX_ANIM/SERIES/EP/TAG
  基础绘制      F() mix() ease() bp() txt() panel() circle() arrow_h()
  CUR_IMG/tile  帧缓存 + 位图加载（贴截图用，见 references/pitfalls.md A2/A3/A4）
  chrome()      顶部标识 + 页标题 + 底部按章分块的时间轴
  make_ch(i)    章封生成器
  draw_*()      每镜一个，签名 (d, t, dur)
  LIVE_BEATS    终端实录的 11 拍（真实命令与输出）
  CHAIN_FILES   主链页每跳的文件全文
  SEGS          镜头表
  TTS / render_segment / assemble

用法:  python make_video.py             # 全量
       python make_video.py --preview   # 每段只渲 2.5s 样片
       python make_video.py --remux     # 只重拼音轨与封装
改稿:  讲稿改 SEGS[i]['narr']；动画改 draw_*；
       只改动画不改文本时，必须手工删 _video_work/{TAG}segNN.mp4（缓存键是讲稿哈希）
"""
import os
import sys
import json
import hashlib
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, '_video_work')
OUT = os.path.join(HERE, '..', '线路GIM拆解讲解视频.mp4')

W, H = 1920, 1080
FPS = 20
TAIL = 0.7                      # 每段结尾留白(秒)
BG = (15, 23, 42)
PANEL = (30, 41, 59)
PANEL2 = (23, 33, 54)
BORDER = (51, 65, 85)
BLUE = (37, 99, 235)
CYAN = (34, 211, 238)
AMBER = (245, 158, 11)
GREEN = (34, 197, 94)
RED = (239, 68, 68)
FG = (226, 232, 240)
MUTED = (148, 163, 184)

FFMPEG = 'ffmpeg'
FFPROBE = 'ffprobe'

# ---------------------------------------------------------------- 基础绘制
_FONT_CACHE = {}


def F(kind, size):
    from PIL import ImageFont
    key = (kind, size)
    if key not in _FONT_CACHE:
        paths = {
            'bold': ['C:/Windows/Fonts/msyhbd.ttc', 'C:/Windows/Fonts/msyh.ttc'],
            'reg': ['C:/Windows/Fonts/msyh.ttc'],
            'mono': ['C:/Windows/Fonts/consolab.ttf', 'C:/Windows/Fonts/consola.ttf'],
        }[kind]
        for p in paths:
            if os.path.exists(p):
                _FONT_CACHE[key] = ImageFont.truetype(p, size)
                break
        else:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def mix(base, fg, a):
    a = max(0.0, min(1.0, a))
    return tuple(int(base[i] + (fg[i] - base[i]) * a) for i in range(3))


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


CUR_IMG = [None]      # 当前帧的 PIL Image：需要贴位图（截图）的段用它 paste
_TILE = {}


def tile(path, size):
    """加载并缓存一张位图，等比缩放到 size。"""
    key = (path, size)
    if key not in _TILE:
        from PIL import Image
        im = Image.open(path).convert('RGB')
        im = im.resize(size, Image.LANCZOS)
        _TILE[key] = im
    return _TILE[key]


ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')

MAX_ANIM = 56.0        # 动画最多用 56 秒铺完：讲稿长时早铺完、停在完成画面，不要拖成空页


def bp(t, dur, start_f, span=0.06):
    """段内节拍：start_f(占比) 开始、span(占比)时长内的缓动进度 0..1。"""
    eff = min(dur, MAX_ANIM)
    return ease((t - start_f * eff) / (span * eff))


def txt(d, xy, s, size, color=FG, a=1.0, bold=False, mono=False):
    if a <= 0.02:
        return 0
    # Consolas 无中文字形：含中文时回退常规字体，避免出现方块
    if mono and any('\u4e00' <= ch <= '\u9fff' for ch in s):
        mono = False
    kind = 'mono' if mono else ('bold' if bold else 'reg')
    f = F(kind, size)
    d.text(xy, s, font=f, fill=mix(BG, color, a))
    return d.textlength(s, font=f)


def panel(d, box, a=1.0, fill=PANEL, border=BORDER, radius=12):
    if a <= 0.02:
        return
    d.rounded_rectangle(box, radius, fill=mix(BG, fill, a),
                        outline=mix(BG, border, a), width=2)


def arrow_h(d, x0, x1, y, a, color=CYAN, thickness=4, head=14):
    """横向渐进箭头：按 a 画到多长，完成后补箭头。"""
    if a <= 0.02:
        return
    xe = x0 + (x1 - x0) * a
    d.line([x0, y, xe, y], fill=mix(BG, color, a), width=thickness)
    if a > 0.85:
        d.polygon([(x1, y), (x1 - head, y - head * 0.6),
                   (x1 - head, y + head * 0.6)], fill=mix(BG, color, a))


def circle(d, xy, r, a, color=CYAN):
    if a <= 0.02:
        return
    x, y = xy
    d.ellipse([x - r, y - r, x + r, y + r], fill=mix(BG, color, a))


# ---------------------------------------------------------------- 全局时间轴
DURS = []
CHAP = ['序', '第 1 章 容器', '第 2 章 层级', '第 3 章 格式',
        '第 4 章 设备', '第 5 章 规范']

# 章封（转场页）文案
CH_META = [
    ('01', '容 器', '784 字节的头  ·  四个目录  ·  十一个字段', '一个文件，怎么把整个工程装进去'),
    ('02', '层 级', '工程  ·  分段  ·  耐张段  ·  设备  ·  部件', '五级是怎么定的，又是怎么裂开的'),
    ('03', '格 式', 'cbm  ·  fam  ·  dev  ·  phm  ·  mod  ·  stl', '六种文件，排成层级链与模型链'),
    ('04', '设 备', '四类设备  ·  三种指针', '走到第五级，最小的单元是谁'),
    ('05', '规 范', '六个工程  ·  四种定义', '标准怎么写，文件怎么填'),
]

# 分段缓存标签：讲稿/动画改版后改这个值，旧分段自动失效（不用手工删 _video_work）
TAG = 'v7'


SERIES = '从零开始学国网 GIM 标准'
EP = 'EP01'


def bg_grid(d):
    """底色保持纯净：不加网格，避免干扰画面内容。"""
    return


def title_card(d, t):
    """开场标题卡：系列名 + 本期名，2.6s 后淡出。"""
    if t > 3.4:
        return
    a = 1.0 if t < 2.6 else max(0.0, 1 - (t - 2.6) / 0.8)
    d.rectangle([0, 0, W, H], fill=BG)
    bg_grid(d)
    d.rectangle([0, 0, W, 6], fill=BLUE)
    # 系列名
    t1 = SERIES
    f1 = F('bold', 76)
    w1 = d.textlength(t1, font=f1)
    d.text(((W - w1) / 2, 400), t1, font=f1, fill=mix(BG, FG, a))
    # 琥珀短线
    d.rectangle([(W - 220) / 2, 500, (W + 220) / 2, 505], fill=mix(BG, AMBER, a))
    # 本期名
    t2 = '第 1 期 · 一条 .gim 文件里到底装了什么'
    f2 = F('reg', 38)
    w2 = d.textlength(t2, font=f2)
    d.text(((W - w2) / 2, 540), t2, font=f2, fill=mix(BG, MUTED, a))
    # 角标
    f3 = F('mono', 24)
    d.text((70, 60), EP, font=f3, fill=mix(BG, AMBER, a))
    d.text((W - 190, H - 90), 'GIM · 线路篇', font=F('reg', 24),
           fill=mix(BG, MUTED, a * 0.8))


def make_ch(i):
    """章封（转场页）：大号章号 + 章名 + 一句引导 + 五章进度点。"""
    num, nm, sub, lead = CH_META[i]

    def _draw(d, t, dur):
        a0 = bp(t, dur, 0.04, span=0.12)
        f = F('bold', 240)
        w = d.textlength(num, font=f)
        d.text(((W - w) / 2, 150 + int(22 * (1 - ease(min(a0 * 1.5, 1))))),
               num, font=f, fill=mix(BG, (30, 64, 175), a0))

        a1 = bp(t, dur, 0.20, span=0.12)
        f2 = F('bold', 96)
        w2 = d.textlength(nm, font=f2)
        d.text(((W - w2) / 2, 500), nm, font=f2, fill=mix(BG, FG, a1))

        # 章名下的琥珀短线：从中间向两侧展开，收束这一页
        a4 = bp(t, dur, 0.70, span=0.16)
        if a4 > 0.01:
            half = 92 * ease(a4)
            d.rectangle([W / 2 - half, 618, W / 2 + half, 622],
                        fill=mix(BG, AMBER, a4))

        a2 = bp(t, dur, 0.36, span=0.08)
        f3 = F('reg', 30)
        w3 = d.textlength(sub, font=f3)
        d.text(((W - w3) / 2, 660), sub, font=f3, fill=mix(BG, MUTED, a2))

        a3 = bp(t, dur, 0.50, span=0.08)
        f4 = F('reg', 31)
        w4 = d.textlength(lead, font=f4)
        d.text(((W - w4) / 2, 714), lead, font=f4, fill=mix(BG, (125, 211, 252), a3))

        for k in range(5):
            aa = bp(t, dur, 0.60 + (0.07 if k == i else 0.0))
            cx = W / 2 + (k - 2) * 48
            if k == i:
                d.ellipse([cx - 10, 812 - 10, cx + 10, 812 + 10],
                          fill=mix(BG, AMBER, aa))
            else:
                d.ellipse([cx - 5, 812 - 5, cx + 5, 812 + 5],
                          fill=mix(BG, (71, 85, 105), aa))
        txt(d, (W / 2 + 132, 800), f'{i + 1} / 5', 22, MUTED,
            a=bp(t, dur, 0.86), mono=True)

    return _draw


def chrome(d, seg, t, dur):
    """顶部系列标识 + 标题；底部按「章」分块的时间轴。"""
    bg_grid(d)
    d.rectangle([0, 0, W, 6], fill=BLUE)
    txt(d, (70, 42), f'{SERIES} · {EP}', 25, AMBER, bold=True)

    if not SEGS[seg].get('plain'):
        txt(d, (70, 84), SEGS[seg]['title'], 54, FG, bold=True)
        d.rectangle([70, 168, 70 + 330, 171], fill=AMBER)

    # ---- 底部时间轴：按章分块 + 章内小节刻度 ----
    ty = H - 58
    x0, x1 = 70, W - 70
    segd = [x + TAIL for x in DURS]
    total = sum(segd) or 1.0
    pos, acc = [], 0.0
    for x in segd:
        pos.append((acc, acc + x))
        acc += x

    def px(f):
        return x0 + (x1 - x0) * f / total

    # 章区间
    chs = []
    for i, sg in enumerate(SEGS):
        c = sg['ch']
        if chs and chs[-1][0] == c:
            chs[-1][2] = pos[i][1]
        else:
            chs.append([c, pos[i][0], pos[i][1]])

    now = pos[seg][0] + min(t, dur)
    for c, s0, s1 in chs:
        bx0, bx1 = px(s0) + 2, px(s1) - 5
        if bx1 - bx0 < 2:
            continue
        if s1 <= now:
            d.rounded_rectangle([bx0, ty, bx1, ty + 6], 3, fill=BLUE)
        elif s0 >= now:
            d.rounded_rectangle([bx0, ty, bx1, ty + 6], 3, fill=(34, 44, 60))
        else:
            d.rounded_rectangle([bx0, ty, bx1, ty + 6], 3, fill=(34, 44, 60))
            d.rounded_rectangle([bx0, ty, max(bx0 + 3, px(now)), ty + 6], 3, fill=BLUE)

    # 章内小节刻度
    for i in range(len(pos) - 1):
        if SEGS[i + 1]['ch'] == SEGS[i]['ch'] and not SEGS[i + 1].get('plain'):
            tx = px(pos[i][1])
            d.line([tx, ty - 2, tx, ty + 8], fill=(86, 102, 126), width=1)
    # 章边界
    for c, s0, s1 in chs[1:]:
        tx = px(s0)
        d.line([tx, ty - 6, tx, ty + 12], fill=(130, 146, 169), width=2)

    curpx = px(now)
    d.ellipse([curpx - 7, ty - 5, curpx + 7, ty + 9], fill=AMBER)

    # 每个章块上方标章名，当前章高亮 —— 一眼看出总体进展
    cur_ch = SEGS[seg]['ch']
    for c, s0, s1 in chs:
        short = CHAP[c].split(' ')[-1] if c else '序'
        lw = d.textlength(short, font=F('bold', 15))
        cx = (px(s0) + px(s1)) / 2
        act = (c == cur_ch)
        col = AMBER if act else (96, 112, 136)
        txt(d, (cx - lw / 2, ty - 30), short, 15, col, bold=act)
    txt(d, (x1 - 120, ty + 16),
        f'{int(now // 60):02d}:{int(now % 60):02d}', 19, (100, 116, 139), mono=True)

    if seg == 0:
        title_card(d, t)


# ---------------------------------------------------------------- 各段动画
def draw_s1(d, t, dur):                                   # 容器头
    t = max(0.0, t - 2.2)        # 开场标题卡占前 3.4s，内容略微提前铺
    # ---- 左：三段字节块 ----
    blocks = [('魔数', 8, CYAN), ('信息区', 768, BLUE), ('7z 压缩域', None, AMBER)]
    x = 90
    y = 240
    for i_, (name, size, col) in enumerate(blocks):
        a = bp(t, dur, 0.26 + i_ * 0.03, span=0.04)
        w = int((196 if i_ < 2 else 380) * a)
        if w > 8:
            d.rounded_rectangle([x, y, x + w, y + 116], 10,
                                fill=mix(BG, PANEL, 1),
                                outline=mix(BG, col, a), width=3)
            if a > 0.3:
                txt(d, (x + 16, y + 20), name, 28, col, bold=True)
                if size:
                    txt(d, (x + 16, y + 62), f'{size} 字节', 25, FG)
                elif a > 0.7:
                    txt(d, (x + 16, y + 62), '真正的数据', 24, MUTED)
        x += int((214 if i_ < 2 else 400) * a) + 16
    txt(d, (90, 392), '头长 784 = 8 + 768 + 8（六样本一致）', 28, FG,
        a=bp(t, dur, 0.31))
    a = bp(t, dur, 0.36, span=0.05)      # 打字机：解说念到魔数时逐个字符出
    s_ = 'GIMPKGT'[:max(1, int(a * 7.2))]
    txt(d, (90, 448), '魔数: ', 30, MUTED, a=bp(t, dur, 0.33))
    if a > 0.02:
        txt(d, (210, 448), s_, 34, CYAN, mono=True, bold=True)
    if a >= 0.999:
        txt(d, (470, 448), 'T=线路 / S=变电站', 26, MUTED, a=bp(t, dur, 0.44))
    txt(d, (90, 516), '自校验: 1,438,855 = 1,439,639 − 784', 29, FG,
        a=bp(t, dur, 0.74))
    if bp(t, dur, 0.84) > 0.5:
        r = int(24 * bp(t, dur, 0.80))
        circle(d, (136, 590), r, 1, GREEN)
        if r > 8:
            d.line([136 - 8, 590, 136 - 2, 598], fill=(255, 255, 255), width=4)
            d.line([136 - 2, 598, 136 + 9, 581], fill=(255, 255, 255), width=4)
        txt(d, (172, 578), '载荷尺寸精确吻合 → 交付件完整', 27, GREEN,
            a=bp(t, dur, 0.94))
    for i_, s_ in enumerate(['段序漂移 → 按"非空段序列"解析，不按固定下标',
                             '坐标系统: CGCS2000（Q/GDW 11809—2023）']):
        txt(d, (90, 668 + i_ * 54), '•', 28, CYAN, a=bp(t, dur, 0.60 + i_ * 0.30))
        txt(d, (124, 668 + i_ * 54), s_, 27, FG, a=bp(t, dur, 0.60 + i_ * 0.30))

    # ---- 右：文件结构示意（竖切面） ----
    a0 = bp(t, dur, 0.26)
    if a0 > 0.02:
        fx0, fx1 = 1120, 1800
        fy0, fy1 = 240, 700
        d.rounded_rectangle([fx0, fy0, fx1, fy1], 14,
                            fill=mix(BG, PANEL, a0), outline=mix(BG, BORDER, a0), width=2)
        # 头部条
        hh = int(56 * a0)
        if hh > 2:
            d.rounded_rectangle([fx0 + 14, fy0 + 14, fx1 - 14, fy0 + 14 + hh], 6,
                                fill=mix(BG, AMBER, a0 * 0.9))
            txt(d, (fx0 + 28, fy0 + 26), '头 784 B（魔数 + 信息区）', 22,
                (30, 25, 10), a=a0, bold=True)
        # 压缩域
        a1 = bp(t, dur, 0.29)
        if a1 > 0.02:
            top = fy0 + 92
            d.rounded_rectangle([fx0 + 14, top, fx1 - 14, fy1 - 20], 8,
                                fill=mix(BG, PANEL2, a1), outline=mix(BG, CYAN, a1), width=2)
            txt(d, (fx0 + 34, top + 18), '7z 压缩域', 26, CYAN, a=a1, bold=True)
            for k, nm in enumerate(['Cbm  层级与装配', 'Dev  设备定义'
                                    '（示意）', 'Phm  零件拆分', 'Mod  几何与坐标']):
                if nm == 'Dev  设备定义（示意）':
                    nm = 'Dev  设备定义'
                txt(d, (fx0 + 40, top + 74 + k * 52), nm, 24, FG,
                    a=bp(t, dur, 0.42 + k * 0.04))
        # 旁注
        txt(d, (1120, 748), '一个 .gim = 784 B 头 + 7z 压缩域',
            24, MUTED, a=bp(t, dur, 0.86))
        txt(d, (1120, 790), '头是明文，能直接读；内容是压缩的，要先解包',
            24, MUTED, a=bp(t, dur, 0.90))


def draw_s2(d, t, dur):                                   # 四目录
    """标准侧只讲"四个目录 + 每类文件的职责"（Q/GDW 11809—2023 §6.2/§6.3），
    数量单独放进"本样本实测"，不把某一个包的文件数说成格式规定。"""
    a0 = bp(t, dur, 0.03)
    panel(d, (90, 184, 1180, 226), a0, fill=PANEL2, border=CYAN, radius=8)
    txt(d, (110, 192),
        '前置：这 1,394 个文件都在 784 字节头之后的压缩域里 —— 先读头确认 GIMPKGT / QGDW2·2023，再解包',
        17, CYAN, a=a0)

    rows = [('CBM', '*.cbm 组装模型 + *.fam',
             '组织层级：引用物理模型与本层属性'),
            ('DEV', '*.dev 物理模型 + *.fam',
             '这是什么：引用几何模型组与属性'),
            ('PHM', '*.phm 几何模型组',
             '由哪些零件组成：引用 1..n 个几何'),
            ('MOD', '*.mod 参数化 / *.stl 面片',
             '长什么样：几何模型本体')]
    for i_, (name, files, desc) in enumerate(rows):
        a = bp(t, dur, 0.06 + i_ * 0.09)
        yy = 240 + i_ * 116
        panel(d, (90, yy, 1180, yy + 96), a)
        txt(d, (116, yy + 24), name, 34, CYAN, a=a, mono=True, bold=True)
        txt(d, (226, yy + 30), files, 22, AMBER, a=bp(t, dur, 0.08 + i_ * 0.09),
            mono=True)
        txt(d, (580, yy + 32), desc, 22, FG, a=bp(t, dur, 0.10 + i_ * 0.09))

    # —— 标准要求 ——
    a1 = bp(t, dur, 0.70)
    panel(d, (1220, 240, 1830, 470), a1, border=BLUE)
    txt(d, (1246, 256), '标准要求', 26, BLUE, a=a1, bold=True)
    txt(d, (1246, 292), 'Q/GDW 11809—2023 §6.2 / §6.3', 19, MUTED,
        a=bp(t, dur, 0.71), mono=True)
    for k, s_ in enumerate(['存储域含四个目录：CBM / DEV / PHM / MOD',
                            '文件类型与引用职责固定',
                            '数量不作规定 —— 由工程规模决定']):
        txt(d, (1246, 340 + k * 42), '·', 22, BLUE, a=bp(t, dur, 0.72 + k * 0.02))
        txt(d, (1268, 340 + k * 42), s_, 21, FG, a=bp(t, dur, 0.72 + k * 0.02))

    # —— 本样本实测 ——
    a2 = bp(t, dur, 0.80)
    panel(d, (1220, 500, 1830, 800), a2, border=AMBER)
    txt(d, (1246, 516), '本样本实测（line04）', 23, AMBER, a=a2, bold=True)
    txt(d, (1246, 556), '1,394 个文件 · 13.81 MB', 24, FG,
        a=bp(t, dur, 0.82), mono=True)
    for k, s_ in enumerate(['Cbm 499 + 350 fam', 'Dev 197 + 197 fam',
                            'Phm 79', 'Mod 31 + 41 stl']):
        txt(d, (1246, 606 + k * 36), s_, 22, MUTED,
            a=bp(t, dur, 0.83 + k * 0.005), mono=True)
    txt(d, (1246, 760), '换工程数字全变，目录与职责不变', 20, MUTED,
        a=bp(t, dur, 0.84))

    # —— 提醒 ——
    a3 = bp(t, dur, 0.54)
    panel(d, (90, 812, 1830, 896), a3, fill=PANEL2)
    txt(d, (116, 836),
        '口诀：Cbm 管谁挂在谁下面 · Dev 管这是什么 · Phm 管由哪些零件组成 · Mod 管长什么样、在哪',
        21, AMBER, a=a3)


def draw_s3(d, t, dur):                                   # 格式①②
    a = bp(t, dur, 0.04)
    panel(d, (90, 240, 990, 560), a)
    txt(d, (110, 252), 'F4 塔位节点 .cbm（原样节选）', 24, MUTED, a=a)
    lines = ['ENTITYNAME    = F4System',
             'GROUPTYPE     = TOWER',
             'BLHA = 27.7452,112.6487,60.0,433.8',
             'TOWERS.NUM=1   TOWER0=6b406cf4….cbm',
             'STRINGS.NUM=16  STRING0.GPOINT=前地2']
    ac = bp(t, dur, 0.10)          # 代码整块出现：逐行淡入会打断阅读
    for i, s in enumerate(lines):
        txt(d, (116, 296 + i * 48), s, 24, FG, a=ac, mono=True)
    parts = ['①纬度', '②经度', '③高程(m)', '④北方向偏角(°)']
    for i, p_ in enumerate(parts):
        a2 = bp(t, dur, 0.40 + i * 0.05)
        txt(d, (116 + i * 212, 570), p_, 24, AMBER, a=a2, bold=True)
    txt(d, (90, 614), 'BLHA 四值依 Q/GDW 11809—2023', 24, MUTED, a=bp(t, dur, 0.58))
    a3 = bp(t, dur, 0.28)
    panel(d, (90, 652, 990, 730), a3, fill=PANEL2)
    txt(d, (116, 670), '指针 XXXn=uuid.cbm  <->  计数键 XXXs.NUM 成对出现', 25, CYAN, a=a3)
    a4 = bp(t, dur, 0.13)
    panel(d, (1030, 240, 1830, 560), a4)
    txt(d, (1050, 252), 'F2 层 .fam 三段式（原样节选）', 24, MUTED, a=a4)
    fam = [('电压等级', 'VOLTAGE', 'AC500kV'),
           ('回路数', 'LOOPNUMBER', '1'),
           ('导线分裂数', 'SPLITNUMBER', '6'),
           ('沿线海拔', 'ELEVATION', '40m-50m')]
    af = bp(t, dur, 0.66)          # 属性行整块出现
    for i, (cn, en, v) in enumerate(fam):
        ab = af
        y = 296 + i * 58
        txt(d, (1056, y), cn, 25, CYAN, a=ab)
        txt(d, (1210, y), '=', 25, MUTED, a=ab)
        txt(d, (1240, y), en, 25, AMBER, a=ab, mono=True)
        txt(d, (1470, y), '=', 25, MUTED, a=ab)
        txt(d, (1500, y), v, 25, FG, a=ab, mono=True)
    txt(d, (1056, 524), '空值也占一行，解析别丢字段', 24, MUTED, a=bp(t, dur, 0.82))
    a5 = bp(t, dur, 0.86)
    panel(d, (1030, 600, 1830, 730), a5, fill=PANEL2)
    txt(d, (1056, 618), '挂靠靠 BASEFAMILY 指针，不靠同名', 25, CYAN, a=a5)
    arrow_h(d, 1080, 1560, 692, bp(t, dur, 0.90))
    txt(d, (1080, 666), '.dev ──BASEFAMILY──> .fam', 22, MUTED,
        a=bp(t, dur, 0.92), mono=True)


def draw_s4(d, t, dur):                                   # 格式③④
    a = bp(t, dur, 0.04)
    panel(d, (640, 232, 1080, 378), a)
    txt(d, (690, 256), 'DEV 挂点串(STRING)', 28, FG, a=a, bold=True)
    txt(d, (690, 296), '组合设备：由多个子设备拼成', 23, MUTED, a=bp(t, dur, 0.08))
    txt(d, (690, 330), '例：SOLIDMODELS.NUM = 116', 23, AMBER,
        a=bp(t, dur, 0.10))
    a2 = bp(t, dur, 0.16)
    panel(d, (170, 520, 620, 650), a2)
    txt(d, (196, 545), '子设备 .dev（金具/绝缘子）', 26, FG, a=a2)
    txt(d, (196, 595), '恰两层，0 条更深', 23, MUTED, a=bp(t, dur, 0.24))
    a3 = bp(t, dur, 0.36)
    panel(d, (1120, 520, 1570, 650), a3)
    txt(d, (1146, 545), '.phm 零件表（叶子）', 26, FG, a=a3)
    txt(d, (1146, 590), 'SOLIDMODEL0 → .mod', 23, MUTED, a=bp(t, dur, 0.44), mono=True)
    txt(d, (1146, 620), '.mod / .stl = 真正的几何', 22, CYAN, a=bp(t, dur, 0.50))
    # 连接线：DEV 卡底边中点垂下 → 横向分叉 → 落到两张子卡顶边（带向下箭头）
    DX, DB = 860, 378                 # DEV 卡中心 x / 底边 y
    LX, RX = 395, 1345                # 左、右子卡中心 x
    TY, MY = 520, 440                 # 子卡顶边 y / 折线横向段 y
    d.line([DX, DB, DX, MY], fill=mix(BG, MUTED, bp(t, dur, 0.18)), width=4)
    al = bp(t, dur, 0.22)
    d.line([DX, MY, LX, MY], fill=mix(BG, CYAN, al), width=4)
    d.line([LX, MY, LX, TY - 16], fill=mix(BG, CYAN, al), width=4)
    if al > 0.85:
        d.polygon([(LX, TY), (LX - 11, TY - 17), (LX + 11, TY - 17)],
                  fill=mix(BG, CYAN, 1))
    ar = bp(t, dur, 0.40)
    d.line([DX, MY, RX, MY], fill=mix(BG, AMBER, ar), width=4)
    d.line([RX, MY, RX, TY - 16], fill=mix(BG, AMBER, ar), width=4)
    if ar > 0.85:
        d.polygon([(RX, TY), (RX - 11, TY - 17), (RX + 11, TY - 17)],
                  fill=mix(BG, AMBER, 1))
    txt(d, (330, 396), 'SOLIDMODELn → .dev  ×7,676', 24, CYAN,
        a=bp(t, dur, 0.28), mono=True, bold=True)
    txt(d, (1006, 396), 'SOLIDMODELn → .phm  ×79', 24, AMBER,
        a=bp(t, dur, 0.48), mono=True)
    a4 = bp(t, dur, 0.42)
    panel(d, (170, 700, 1570, 796), a4, fill=PANEL2)
    txt(d, (200, 728), '197 个 dev = 组合 118（全部挂点串）+ 叶子 79', 28, FG,
        a=a4, bold=True)
    for i, s in enumerate(['键名相同, 含义按值后缀分层:',
                           '  → .dev  = 装配（组合→子设备）',
                           '  → .phm  = 零件表（叶子→几何）',
                           '几何链路: dev→phm→mod/stl',
                           '三跳全指针, dev 不直挂几何']):
        txt(d, (170, 836 + i * 46), s, 25, FG if i == 0 else MUTED,
            a=bp(t, dur, 0.62 + i * 0.06))


def draw_s5(d, t, dur):                                   # 几何
    fams = [('CODE=', 'Point/Line 几何族', 16, CYAN),
            ('Bolt…', '螺栓孔位族', 8, AMBER),
            ('type=', 'KV 参数族', 4, GREEN),
            ('HNum…', '塔腿族', 3, BLUE)]
    for i, (key, name, n, col) in enumerate(fams):
        a = bp(t, dur, 0.20 + i * 0.06)
        yy = 240 + i * 108
        panel(d, (90, yy, 900, yy + 92), a)
        txt(d, (116, yy + 16), key, 28, col, a=a, mono=True, bold=True)
        txt(d, (330, yy + 20), name, 26, FG, a=bp(t, dur, 0.22 + i * 0.06))
        txt(d, (760, yy + 20), f'× {n}', 28, AMBER,
            a=bp(t, dur, 0.24 + i * 0.06), mono=True)
    txt(d, (90, 700), '判型只认第一行键（四种格式共用 .mod 扩展名）', 27, FG,
        a=bp(t, dur, 0.50))
    a = bp(t, dur, 0.16)          # 先立面板框，内容随“STL 两种表达”填
    panel(d, (990, 240, 1830, 640), a)
    txt(d, (1010, 252), '.stl —— Binary（STL 另有 ASCII 表达）', 24, MUTED, a=a)
    blocks = [('80 B 头', 150), ('uint32 数', 130), ('50 B × 三角形', 380)]
    x = 1010
    for i, (name, w) in enumerate(blocks):
        ab = bp(t, dur, 0.50 + i * 0.05)
        bw = int(w * ab)
        if bw > 6:
            d.rounded_rectangle([x, 300, x + bw, 370], 8,
                                fill=mix(BG, PANEL2, 1),
                                outline=mix(BG, CYAN, ab), width=2)
            if ab > 0.4:
                txt(d, (x + 12, 316), name, 22, FG)
        x += int(w * ab) + 14
    txt(d, (1010, 410), '三角形数 = 3638（从偏移 80 读出）', 24, FG,
        a=bp(t, dur, 0.76), mono=True)
    if bp(t, dur, 0.80) > 0.5:
        txt(d, (1010, 470), '√ 84 + 50×3638 = 181,984 B 自校验通过', 26, GREEN,
            a=bp(t, dur, 0.86), mono=True)
    txt(d, (990, 660), '先分 Binary/ASCII，再进 .mod 认首行键', 24, MUTED,
        a=bp(t, dur, 0.92))


def draw_s6(d, t, dur):                                   # 下钻
    nodes = [('project.cbm', 'SUBSYSTEM', 230, 1),
             ('F1System ×1', 'SECTIONn', 326, 2),
             ('F2System ×2', 'STRAINSECTIONn', 422, 3),
             ('F3System ×4', 'GROUPn', 518, 4),
             ('F4System 唯一148 / 引用150', 'TOWER0/STRINGn', 614, 5)]
    for i, (name, key, y, lv) in enumerate(nodes):
        a = bp(t, dur, 0.05 + i * 0.11)
        x = 120 + (lv - 1) * 60
        panel(d, (x, y, x + 520, y + 68), a)
        txt(d, (x + 20, y + 16), name, 26, FG, a=a)
        if i < len(nodes) - 1:
            a2 = bp(t, dur, 0.10 + i * 0.11)
            d.line([x + 40, y + 68, x + 40, y + 92],
                   fill=mix(BG, CYAN, a2), width=3)
            txt(d, (x + 58, y + 70), key, 20, CYAN, a=a2, mono=True)
    for i, s in enumerate(['证明① NUM 计数键 == 实际子键个数',
                           '证明② 读回 ENTITYNAME == 预期身份']):
        a = bp(t, dur, 0.46 + i * 0.10)
        circle(d, (1010, 300 + i * 96), 16, a, GREEN)
        txt(d, (1040, 284 + i * 96), s, 26, FG, a=a)
    txt(d, (1000, 520), 'F3 --GROUPn--> F4:', 26, FG, a=bp(t, dur, 0.62))
    txt(d, (1000, 568), '引用 150 条', 30, AMBER, a=bp(t, dur, 0.66), bold=True)
    txt(d, (1000, 616), '唯一 148 个', 30, GREEN, a=bp(t, dur, 0.72), bold=True)
    txt(d, (1000, 668), '2 组被两耐张段共用 → 按 uuid 去重', 23, MUTED,
        a=bp(t, dur, 0.78))


def draw_s7(d, t, dur):                                   # 层级 + 数量（对齐 line04）
    CY = 432
    cols = [('F1', '工程', 1, '× 1', 240, CYAN, ''),
            ('F2', '分段', 2, '× 2', 580, CYAN, 'SUBSYSTEM'),
            ('F3', '耐张段', 4, '× 4', 920, CYAN, 'SECTIONn'),
            ('F4', '设备组', 3, '× 148', 1260, AMBER, 'GROUPn'),
            ('L5', '部件', 3, '× 343', 1600, AMBER, 'SUBDEVICEn')]

    for ci, (tag, nm, n, cnt, x, col, key) in enumerate(cols):
        a = bp(t, dur, 0.05 + ci * 0.13)
        ys = [CY + (k - (n - 1) / 2) * 68 for k in range(n)]
        for y in ys:
            circle(d, (x, y), 10 + 15 * a, a, col)
        txt(d, (x - 52, 236), tag, 17, col if ci < 3 else AMBER, a=a, mono=True, bold=True)
        txt(d, (x - 34, 262), nm, 20, FG, a=bp(t, dur, 0.06 + ci * 0.13), bold=True)
        txt(d, (x - 42, 566), cnt, 28, col if ci < 3 else AMBER,
            a=bp(t, dur, 0.07 + ci * 0.13), bold=True, mono=True)
        if n == 3 and ci >= 3:
            txt(d, (x - 10, ys[-1] + 40), '…', 28, col, a=bp(t, dur, 0.09 + ci * 0.13), bold=True)
        if key:
            txt(d, (x - 210, CY - 34), key, 13, MUTED, a=bp(t, dur, 0.09 + ci * 0.13), mono=True)

    for ci in range(4):
        a = bp(t, dur, 0.10 + ci * 0.13)
        x0 = cols[ci][4] + 54
        x1 = cols[ci + 1][4] - 54
        d.line([x0, CY, x0 + (x1 - x0) * a, CY], fill=mix(BG, (100, 116, 139), a), width=3)

    for ci in range(4):
        t0 = (0.15 + ci * 0.13) * dur
        t1 = t0 + 0.09 * dur
        if t < t0:
            break
        x0 = cols[ci][4] + 54
        x1 = cols[ci + 1][4] - 54
        if t <= t1:
            q = ease((t - t0) / (t1 - t0))
            circle(d, (x0 + (x1 - x0) * q, CY), 10, 1, AMBER)
        else:
            nxt = 1e9 if ci + 1 >= 4 else (0.15 + (ci + 1) * 0.13) * dur
            if t < nxt:
                circle(d, (x1, CY), 10, 1, AMBER)

    a = bp(t, dur, 0.46)
    txt(d, (240, 634), '引用边 779 条  >  唯一节点 499 个  →  有文件被多个父亲引用',
        22, FG, a=a)
    txt(d, (240, 670), '所以它是引用图，不是一棵严格的树', 22, AMBER,
        a=bp(t, dur, 0.62), bold=True)
    for i_, s_ in enumerate(['工程层级 = 逻辑', '文件引用 = 指针',
                             '唯一节点 = 去重', '引用边 = 指向关系']):
        a2 = bp(t, dur, 0.66 + i_ * 0.05)
        bx = 240 + i_ * 372
        panel(d, (bx, 712, bx + 348, 758), a2, fill=PANEL2)
        txt(d, (bx + 18, 726), s_, 19, CYAN, a=a2)

    txt(d, (240, 786), 'walk 判据：值以 .cbm 结尾 且 键不带 .NUM → 子指针；没有子指针 = 叶子',
        20, FG, a=bp(t, dur, 0.80))
    leafs = [('Tower_Device', '141'), ('WIRE', '138'),
             ('Wire_Device', '48'), ('CROSS', '16')]
    for i_, (nm, nn) in enumerate(leafs):
        a2 = bp(t, dur, 0.84 + i_ * 0.035)
        txt(d, (240 + i_ * 300, 820), nm, 16, MUTED, a=a2, mono=True)
        txt(d, (240 + i_ * 300, 842), nn, 26, GREEN, a=a2, bold=True, mono=True)
    txt(d, (240, 890), '↑ 叶子普查 = walk 的真实输出：499 个节点全部可达，零孤儿',
        16, MUTED, a=bp(t, dur, 0.96))


# ---------------------------------------------------------------- 分镜动画
def draw_a1(d, t, dur):                                   # 开场
    txt(d, (90, 214), '一个文件  ·  五层结构  ·  六种格式  ·  三种指针',
        34, CYAN, a=bp(t, dur, 0.03), bold=True)

    stds = [
        ('Q/GDW 11809—2023', '模型数据交互规范',
         '数据怎么存：容器、目录、格式、引用关系、属性表', CYAN),
        ('Q/GDW 11810.2—2023', '建模规范 · 架空线路',
         '模型怎么建：几何细度、属性细度、设备关键字表', GREEN),
        ('Q/GDW 11798.2—2023', '技术导则 · 架空线路',
         '设计怎么用：哪类对象用 mod，哪类只能用 stl', AMBER),
    ]
    for i, (code, name, desc, col) in enumerate(stds):
        a = bp(t, dur, 0.12 + i * 0.07)
        x = 90 + i * 580
        panel(d, (x, 296, x + 540, 468), a)
        d.rectangle([x, 296, x + 6, 468], fill=mix(BG, col, a))
        txt(d, (x + 26, 316), code, 23, col, a=a, mono=True, bold=True)
        txt(d, (x + 26, 352), name, 30, FG, a=a, bold=True)
        txt(d, (x + 26, 408), desc, 20, MUTED, a=bp(t, dur, 0.16 + i * 0.07))

    steps = ['容器', '层级', '格式', '设备', '规范']
    for i, s_ in enumerate(steps):
        a = bp(t, dur, 0.40 + i * 0.05)
        x = 90 + i * 342
        panel(d, (x, 556, x + 302, 638), a, fill=PANEL2,
              border=CYAN if i == 0 else BORDER)
        txt(d, (x + 22, 580), f'0{i + 1}', 28, AMBER, a=a, mono=True, bold=True)
        txt(d, (x + 84, 584), s_, 30, FG, a=a, bold=True)
        if i < 4:
            txt(d, (x + 308, 582), '›', 34, mix(BG, MUTED, a), a=a)

    txt(d, (90, 712), '样本：XX线Π接段 500kV 线路工程 · 1.44 MB · 解包 1,394 个文件（工程名已脱敏）',
        24, MUTED, a=bp(t, dur, 0.68))
    txt(d, (90, 784), '这一集不讲软件怎么点，只讲文件里写了什么、标准为什么要这么定。',
        28, FG, a=bp(t, dur, 0.80))


def draw_a2(d, t, dur):                                   # 容器头 784
    FIELDS = [('文件标识', 16), ('文件名称', 256), ('文件编辑者', 64),
              ('文件编辑单位', 256), ('软件名称', 128), ('创建时间', 16),
              ('软件主版号', 8), ('软件次版号', 8),
              ('标准主版本号', 8), ('标准次版本号', 8), ('存储域大小', 16)]
    unit = 600 / 256.0
    total = 0
    for i, (nm, n) in enumerate(FIELDS):
        a = bp(t, dur, 0.05 + i * 0.048)
        if a <= 0.02:
            continue
        y = 208 + i * 44
        txt(d, (90, y), nm, 22, FG, a=a)
        w = max(7, int(n * unit * a))
        d.rounded_rectangle([448, y + 5, 448 + w, y + 29], 4,
                            fill=mix(BG, CYAN if i % 2 == 0 else BLUE, a))
        txt(d, (1078, y), str(n), 23, AMBER if n >= 128 else MUTED, a=a, mono=True)
        if a >= 1:
            total += n
    if total:
        txt(d, (930, 706), f'= {total}', 42, GREEN, a=bp(t, dur, 0.60),
            mono=True, bold=True)

    a = bp(t, dur, 0.55)
    panel(d, (1180, 208, 1830, 430), a)
    txt(d, (1206, 226), '合计 = 784 字节', 30, CYAN, a=a, bold=True)
    txt(d, (1206, 274), '16+256+64+256+128+16', 22, MUTED, a=a, mono=True)
    txt(d, (1206, 306), '+ 8+8+8+8 + 16', 22, MUTED, a=a, mono=True)
    txt(d, (1206, 356), '十一个字段挨着排，不留白、不填充', 19, FG,
        a=bp(t, dur, 0.64))

    a2 = bp(t, dur, 0.70)
    panel(d, (1180, 456, 1830, 624), a2, border=AMBER)
    txt(d, (1206, 470), '这个字段怎么用', 26, AMBER, a=a2, bold=True)
    txt(d, (1206, 510), '它记录压缩域有多少字节', 21, FG, a=bp(t, dur, 0.76))
    txt(d, (1206, 548), '7z 域紧跟在头后面，就是这 1,438,855 字节', 18, MUTED,
        a=bp(t, dur, 0.82))
    txt(d, (1206, 584), '解包时按它定位，不用去扫文件尾', 18, MUTED,
        a=bp(t, dur, 0.88))

    a3 = bp(t, dur, 0.80)
    panel(d, (1180, 636, 1830, 790), a3, fill=PANEL2)
    txt(d, (1206, 652), '别按"非空段"理解', 24, CYAN, a=a3, bold=True)
    txt(d, (1206, 692), '字段值以 NUL 结尾，空字段不留痕迹；', 20, FG, a=a3)
    txt(d, (1206, 724), '多一个"设计单位"段，按下标取就会错位', 20, MUTED,
        a=bp(t, dur, 0.86))


def draw_a4(d, t, dur):                                   # 标准五级
    LV = [('L1', '工程', 'F1System', '表 C.22', '43 个属性', '工程名、编号、电压、起止点', CYAN, '× 1'),
          ('L2', '分段', 'F2System', '表 C.23', '37 个属性', '电压、回路数、长度、起止杆塔', BLUE, '× 2'),
          ('L3', '耐张段', 'F3System', '表 C.24', '14 个属性', '导线地线型号、代表档距、工况', (56, 189, 248), '× 4'),
          ('L4', '设备组', 'F4System', '标准未定', '按 GROUPTYPE 分三套', '塔组 / 导体组 / 通道地物组', (59, 130, 246), '× 148'),
          ('L5', '部件', 'TOWER_DEVICE…', '11810.2 附录 B', '按设备类型定', '塔身、串、基础、线体、附件', AMBER, '× 343')]
    for i, (lv, nm, ent, tb, cnt, desc, col, num) in enumerate(LV):
        a = bp(t, dur, 0.06 + i * 0.09)
        x = 90 + i * 352
        panel(d, (x, 236, x + 330, 636), a)
        d.rectangle([x, 236, x + 330, 241], fill=mix(BG, col, a))
        txt(d, (x + 22, 256), lv, 22, col, a=a, mono=True, bold=True)
        txt(d, (x + 22, 294), nm, 36, FG, a=a, bold=True)
        txt(d, (x + 22, 350), ent, 17, MUTED, a=bp(t, dur, 0.08 + i * 0.09), mono=True)
        txt(d, (x + 22, 396), tb, 21, col, a=bp(t, dur, 0.09 + i * 0.09), bold=True)
        txt(d, (x + 22, 430), cnt, 18, MUTED, a=bp(t, dur, 0.09 + i * 0.09))
        txt(d, (x + 22, 486), desc, 19, FG, a=bp(t, dur, 0.11 + i * 0.09))
        txt(d, (x + 22, 570), num, 34, col, a=bp(t, dur, 0.13 + i * 0.09), bold=True)

    a = bp(t, dur, 0.60)
    panel(d, (90, 676, 1830, 790), a, fill=PANEL2)
    txt(d, (116, 694), '只有前三级在标准里有属性表', 25, AMBER, a=a, bold=True)
    txt(d, (116, 736), '设备级与部件级的属性由建模规范 Q/GDW 11810.2 附录 B 规定；交互规范只管"怎么存、怎么挂"。',
        22, FG, a=bp(t, dur, 0.68))

    a2 = bp(t, dur, 0.78)
    panel(d, (90, 812, 1830, 900), a2, border=AMBER)
    txt(d, (116, 830), '最常见的误读：第二级是「分段」，不是「回路」', 24, AMBER,
        a=a2, bold=True)
    txt(d, (116, 868), '一条线路可以按标段、架设方式、改接范围切段；一个分段里也可以有多回。line06 一棵 F1 挂两条运行线路，那是两个分段。',
        21, FG, a=bp(t, dur, 0.86))


def draw_a5(d, t, dur):                                   # 加法 + 裂变
    txt(d, (90, 206), 'line04 实测：五级各有多少个 cbm', 24, MUTED,
        a=bp(t, dur, 0.03))
    parts = [('1', CYAN), ('1', CYAN), ('2', BLUE), ('4', BLUE), ('148', AMBER), ('343', AMBER)]
    x = 90
    for i, (s_, col) in enumerate(parts):
        a = bp(t, dur, 0.05 + i * 0.05)
        w = d.textlength(s_, font=F('bold', 50))
        txt(d, (x, 238), s_, 50, col, a=a, bold=True, mono=True)
        x += w + 18
        if i < len(parts) - 1:
            txt(d, (x, 246), '+', 34, mix(BG, MUTED, a), a=a)
            x += 34
    a = bp(t, dur, 0.36)
    txt(d, (x + 14, 238), '= 499', 50, GREEN, a=a, bold=True, mono=True)
    txt(d, (x + 14, 300), '一个不多一个不少', 20, MUTED, a=bp(t, dur, 0.42))

    rows = [('L1', '工程', 1, 46, CYAN, '—'),
            ('L2', '分段', 2, 84, BLUE, '× 2'),
            ('L3', '耐张段', 4, 166, (56, 189, 248), '× 2'),
            ('L4', '设备组', 148, 600, (59, 130, 246), '× 37'),
            ('L5', '部件', 343, 700, AMBER, '× 2.3')]
    for i, (lv, nm, n, w, col, k) in enumerate(rows):
        a = bp(t, dur, 0.46 + i * 0.08)
        y = 372 + i * 84
        txt(d, (90, y), lv, 20, col, a=a, mono=True, bold=True)
        txt(d, (140, y - 4), nm, 24, FG, a=a, bold=True)
        d.rounded_rectangle([310, y - 2, 310 + int(w * a), y + 34], 6,
                            fill=mix(BG, col, a))
        txt(d, (310 + w + 16, y - 6), str(n), 32, col, a=a, bold=True, mono=True)
        txt(d, (1700, y), k, 22, MUTED, a=a)

    a = bp(t, dur, 0.86)
    txt(d, (90, 816), 'L3 → L4 是 ×37：4 个耐张段，各自挂 11 / 64 个设备组 —— 组数不是标准常数',
        23, FG, a=a)
    txt(d, (90, 858), '它 = 这个段的塔数 + 档数×相数 + 跨越数；line04：2 塔 + 8 或 61 个导体组 + 1 处跨越',
        21, AMBER, a=bp(t, dur, 0.92))


def draw_a6(d, t, dur):                                   # 每级一把钥匙
    hdr = ('层级跳转', '引用键', '计数键')
    for i, s_ in enumerate(hdr):
        txt(d, (90 + [0, 360, 830][i], 206), s_, 20, MUTED, a=bp(t, dur, 0.04))
    rows = [('根 → 1 级', 'SUBSYSTEM', '—', '表 A.17'),
            ('1 → 2 级', 'SECTION<n>', 'SECTIONS.NUM', '表 A.18'),
            ('2 → 3 级', 'STRAINSECTION<n>', 'STRAINSECTIONS.NUM', '表 A.19'),
            ('3 → 4 级', 'GROUP<n>', 'GROUPS.NUM', '表 A.20'),
            ('4 塔组 → 5', 'TOWER<n> / STRING<n> / BASE<n>', '各自 .NUM', '表 A.21'),
            ('4 导体组 → 5', 'SUBDEVICE<n>', 'SUBDEVICES.NUM', '表 A.22'),
            ('5 级 → 几何', 'OBJECTMODELPOINTER', '—', '表 A.24')]
    for i, (a_, b_, c_, d_) in enumerate(rows):
        aa = bp(t, dur, 0.08 + i * 0.055)
        y = 238 + i * 62
        panel(d, (90, y, 1170, y + 52), aa, fill=PANEL2,
              border=AMBER if i >= 4 else BORDER)
        txt(d, (108, y + 14), a_, 20, MUTED, a=aa)
        txt(d, (360, y + 12), b_, 21, CYAN if i >= 4 else FG, a=aa, mono=True)
        txt(d, (830, y + 12), c_, 21, AMBER, a=aa, mono=True)
        txt(d, (1176, y + 14), d_, 17, (100, 116, 139), a=aa, mono=True)

    tips = [('① NUM 必填', '数量为 0 也要输出，所以"有键无值"'),
            ('② 第四级有三套键', '同是 F4SYSTEM，按 GROUPTYPE 分三套键'),
            ('③ 塔组 BASEFAMILY 是空值', '标准表 A.21 写明"值为空"')]
    tails = ["不等于\u201c没这个键\u201d", "塔组 / 导体组 / 通道地物组", "拿它找 fam 必然落空"]
    for i, (h_, b_) in enumerate(tips):
        aa = bp(t, dur, 0.50 + i * 0.10)
        y = 238 + i * 150
        panel(d, (1270, y, 1830, y + 126), aa, border=AMBER)
        txt(d, (1294, y + 14), h_, 21, AMBER, a=aa, bold=True)
        txt(d, (1294, y + 52), b_, 18, FG, a=bp(t, dur, 0.54 + i * 0.10))
        txt(d, (1294, y + 84), tails[i], 18, MUTED, a=bp(t, dur, 0.56 + i * 0.10))

    a = bp(t, dur, 0.86)
    txt(d, (90, 700), '一级一把钥匙，各级互不通用。只认 SUBDEVICE 的通用遍历器，走到第 1 级就停住了。',
        23, CYAN, a=a, bold=True)
    txt(d, (90, 750), 'GROUPTYPE 三分：TOWER → 塔组（塔 + 串 + 基础）　WIRE → 导体组（一档一相）　CROSS → 通道地物组',
        21, FG, a=bp(t, dur, 0.92))


def draw_a7(d, t, dur):                                   # 下钻：两道证明 + line04 的树
    a = bp(t, dur, 0.04)
    panel(d, (90, 190, 1030, 540), a, fill=(13, 17, 23))
    code = [
        "node = kv(CBM / 'project.cbm')          # 根：只有一行",
        "f1 = kv(CBM / node['SUBSYSTEM'])        # 值就是文件名",
        "assert f1['ENTITYNAME'].upper() == 'F1SYSTEM'",
        "",
        "for i in range(int(f1['SECTIONS.NUM'])):   # 有几条走几条",
        "    f2 = kv(CBM / f1[f'SECTION{i}'])",
        "    assert f2['ENTITYNAME'].upper() == 'F2SYSTEM'",
        "    ..."]
    for k, ln in enumerate(code):
        txt(d, (114, 210 + k * 38), ln, 17, FG if not ln.startswith('    else') else MUTED,
            a=bp(t, dur, 0.03 + k * 0.014), mono=True)

    a = bp(t, dur, 0.15)
    panel(d, (90, 570, 1030, 786), a, border=AMBER)
    txt(d, (116, 586), '每走一步，两道证明', 25, AMBER, a=a, bold=True)
    txt(d, (116, 628), '① 计数键说这层有几条边 —— 用它定循环次数，不靠猜', 20, FG,
        a=bp(t, dur, 0.19))
    txt(d, (116, 672), '② 读回子文件，ENTITYNAME 必须是这一级 —— 才确认站对了', 20, FG,
        a=bp(t, dur, 0.23))
    txt(d, (116, 724), 'SUBSYSTEM 的值是字符串，不是对象：必须先 open 才能读出键。', 18, MUTED,
        a=bp(t, dur, 0.27))

    # ---- 右侧：阅读器里的同一棵树（真实截图，未截入底图）----
    a = bp(t, dur, 0.21)
    txt(d, (1206, 194), '阅读器里的同一棵树', 22, CYAN, a=a, bold=True)

    tw, th = 330, 446
    if CUR_IMG[0] is not None:
        from PIL import Image
        t_ = tile(os.path.join(ASSET, 'tree_panel.png'), (tw, th))
        if a < 0.999:
            t_ = Image.blend(Image.new('RGB', (tw, th), BG), t_, a)
        panel(d, (1200, 230, 1200 + tw + 12, 230 + th + 12), a, fill=PANEL2, border=BORDER)
        CUR_IMG[0].paste(t_, (1206, 236))

    for k, (s_, c_) in enumerate([
            ('阅读器把第二级叫「区段」', FG),
            ('标准文本里叫「分段」', FG),
            ('—— 同一个 F2System', MUTED)]):
        aa = bp(t, dur, 0.33 + k * 0.04)
        txt(d, (1570, 252 + k * 32), s_, 16, c_, a=aa)

    txt(d, (1570, 366), '这一屏不含底图：', 15, MUTED, a=bp(t, dur, 0.46))
    txt(d, (1570, 394), '工程名与包名已替换，', 15, MUTED, a=bp(t, dur, 0.49))
    txt(d, (1570, 422), '只保留层级本身。', 15, MUTED, a=bp(t, dur, 0.52))

    a = bp(t, dur, 0.58)
    txt(d, (1206, 702), '1 个工程 → 2 个分段 → 4 个耐张段', 22, FG, a=a, bold=True)
    txt(d, (1206, 740), '这不是标准的要求，是这个工程的实际切法', 18, MUTED,
        a=bp(t, dur, 0.63))
    txt(d, (1206, 774), '再往下：148 个设备组 → 343 个部件', 19, AMBER,
        a=bp(t, dur, 0.68))

    a = bp(t, dur, 0.76)
    panel(d, (90, 812, 1830, 944), a, fill=PANEL2)
    txt(d, (116, 828), '这一遍走下来的账（line04）', 20, CYAN, a=a, bold=True)
    txt(d, (116, 868), '根 1 行 → F1 1 个 → F2 2 个 → F3 4 个 → F4 150 条引用（唯一 148 个）→ 部件 343 个',
        19, FG, a=bp(t, dur, 0.88))
    txt(d, (116, 906), '每跳一次验一次 ENTITYNAME，断言一次都没落空 —— 这才是"证实自己站对了"的意思',
        18, MUTED, a=bp(t, dur, 0.92))


CHAIN_FILES = {
    'project': ('project.cbm', 1, [
        'SUBSYSTEM=7f9e83d7-754a-6475-….cbm']),
    'F1System': ('7f9e83d7-754a-6475-….cbm', 6, [
        'ENTITYNAME=F1System',
        'BASEFAMILY=7f9e83d7-754a-6475-….fam',
        'SECTIONS.NUM=2',
        'SECTION0=67849309-abd6-2868-….cbm',
        'SECTION1=e1024300-4be6-4d96-….cbm',
        'MATERIALSHEET=']),
    'F2System': ('67849309-abd6-2868-….cbm', 6, [
        'ENTITYNAME=F2System',
        'BASEFAMILY=67849309-abd6-2868-….fam',
        'STRAINSECTIONS.NUM=2',
        'STRAINSECTION0=9686e776-7338-6d50-….cbm',
        'STRAINSECTION1=f18271f9-58ae-4c82-….cbm',
        'MATERIALSHEET=']),
    'F3System': ('9686e776-7338-6d50-….cbm', 15, [
        'ENTITYNAME=F3System',
        'BASEFAMILY=9686e776-7338-6d50-….fam',
        'GROUPS.NUM=11',
        'GROUP0=f3a5338a-4d81-4747-….cbm',
        'GROUP1=043ed551-5a7d-467e-….cbm',
        '… 共 11 条 GROUPn（本耐张段 11 个设备组）']),
    'F4System': ('f3a5338a-4d81-4747-….cbm', 40, [
        'ENTITYNAME=F4System',
        'GROUPTYPE=TOWER',
        'BASEFAMILY=（空）',
        'BLHA=27.745227,112.648678,60.000,433.75',
        'MODLEG=0.000,0.000,0.000,0.000',
        'TOWERS.NUM=1',
        'TOWER0=6b406cf4-41f8-48c3-….cbm',
        'STRINGS.NUM=16',
        'STRING0.STRING=010898fd-52a0-4295-….cbm',
        '… 另有 15 组 STRINGn.STRING / GPOINT']),
    'Tower_Device': ('6b406cf4-41f8-48c3-….cbm', 4, [
        'OBJECTMODELPOINTER=….dev',
        'BASEFAMILY=6b406cf4-41f8-48c3-….fam',
        'TRANSFORMMATRIX=（16 个数，位姿）',
        'ENTITYNAME=Tower_Device']),
}

CHAIN_ATTR = {
    'project': ('（根文件，没有属性文件）', []),
    'F1System': ('工程级 fam：43 个属性，节选', [
        '设计阶段工程名称=XX线Π接段500kV线路工程',
        '线路长度=LINELENGTH=0.100000',
        '杆塔基数=TOWERNUMBER=2']),
    'F2System': ('分段级 fam：37 个属性，节选', [
        '电压等级=VOLTAGE=AC500kV',
        '回路数=LOOPNUMBER=1',
        '线路长度=LINELENGTH=0.049000']),
    'F3System': ('耐张段级 fam：14 个属性，节选', [
        '导线型号=WIRETYPE=JL3/G1A-300/40',
        '代表档距=LP=50.080100',
        '覆冰=ICE=-5,10,15,20（四维工况）']),
    'F4System': ('塔组不挂属性文件', [
        'BASEFAMILY 为空 —— 148 个设备组全空',
        '它的位置写在 BLHA 里（坐标已偏移脱敏）']),
    'Tower_Device': ('部件级 fam：部件属性', [
        '是否绝缘=ISINSULATION=否',
        '部件生产厂家==国网金具库',
        '类型/型号在 dev 的 fam 里']),
}


def draw_s8(d, t, dur):                                   # 主链：每跳一步，摊开一个文件
    chain = [('project', 'SUBSYSTEM', ''), ('F1System', 'SECTIONn', '7f9e83d7'),
             ('F2System', 'STRAINSECTIONn', '67849309'),
             ('F3System', 'GROUPn', '9686e776'),
             ('F4System', 'TOWER0', 'f3a5338a'),
             ('Tower_Device', '', '6b406cf4')]
    n = len(chain)
    xs = [90 + i * 292 for i in range(n)]

    hop_i, hop_p = None, 0.0
    HOP_SPAN = 0.13
    for i in range(n - 1):
        start = 0.10 + i * HOP_SPAN
        if t >= start * dur:
            hop_i = i
            hop_p = min((t - start * dur) / (HOP_SPAN * dur), 1.0)

    # ---- 上排卡片 ----
    for i, (name, key, uid) in enumerate(chain):
        a = 0.55 if (hop_i is None or i > hop_i) else 1.0
        panel(d, (xs[i], 196, xs[i] + 250, 300), a)
        if hop_i is not None and i <= hop_i:
            d.rounded_rectangle((xs[i], 196, xs[i] + 250, 300), 12,
                                fill=mix(BG, PANEL, 1), outline=mix(BG, AMBER, 1), width=3)
        txt(d, (xs[i] + 14, 204), (uid + '….cbm') if uid else 'project.cbm',
            17, CYAN, a=a, mono=True)
        txt(d, (xs[i] + 14, 234), name, 22, FG, a=1.0 if (hop_i is not None and i <= hop_i) else a,
            bold=True)
        if key:
            txt(d, (xs[i] + 14, 272), key, 14, AMBER, a=a * 0.9, mono=True)

    # ---- 飞行 ----
    if hop_i is not None:
        i = hop_i
        key = chain[i][1]
        carried = (chain[i + 1][2] + '….cbm') if chain[i + 1][2] else 'F1….cbm'
        pop = ease(min(hop_p / 0.30, 1.0))
        flight = ease(max(0.0, min((hop_p - 0.25) / 0.55, 1.0)))
        land = ease(max(0.0, (hop_p - 0.80) / 0.20))
        if 0 < hop_p < 0.9:
            ky = 170 - int(14 * pop)
            ka = pop * (1.0 - max(0.0, (hop_p - 0.28) / 0.22))
            sx = xs[i] + 125
            txt(d, (sx - d.textlength(key, font=F('bold', 24)) / 2, ky),
                key, 22, AMBER, a=max(ka, 0), bold=True)
        if 0.02 < flight < 1.0:
            x0, x1 = xs[i] + 125, xs[i + 1] + 125
            fx = x0 + (x1 - x0) * flight
            fy = 340 - int(80 * (1 - abs(2 * flight - 1)))
            for k in range(1, 4):
                q = max(0.0, flight - k * 0.045)
                tx = x0 + (x1 - x0) * q
                ty = 340 - int(80 * (1 - abs(2 * q - 1)))
                circle(d, (tx, ty), 7 - k * 2, 0.5 - k * 0.12, AMBER)
            circle(d, (fx, fy), 13, 1, AMBER)
            circle(d, (fx, fy), 5, 1, (255, 255, 255))
            if carried:
                lw = d.textlength(carried, font=F('mono', 20))
                panel(d, (fx - lw / 2 - 10, fy - 62, fx + lw / 2 + 10, fy - 30),
                      min(flight * 3, 1), fill=PANEL2, border=CYAN, radius=8)
                txt(d, (fx - lw / 2, fy - 57), carried, 20, CYAN, mono=True, bold=True)
        if land > 0.5:
            txt(d, (xs[i + 1] + 14, 304), '读回 ENTITYNAME 一致', 15, GREEN,
                a=(land - 0.5) * 2)

    # ---- 下：当前文件全文 ----
    cur = chain[0][0]
    if hop_i is not None:
        cur = chain[hop_i + 1][0] if hop_p >= 0.85 else chain[hop_i][0]
    fn, total, lines = CHAIN_FILES[cur]
    ap = bp(t, dur, 0.06)

    panel(d, (90, 348, 1150, 762), ap, fill=(13, 17, 23))
    txt(d, (112, 358), '当前文件', 15, MUTED, a=ap)
    txt(d, (196, 356), fn, 17, CYAN, a=ap, mono=True, bold=True)
    txt(d, (1030, 358), f'共 {total} 行', 14, MUTED, a=ap, mono=True)
    for k, ln in enumerate(lines):
        col = AMBER if ('=' in ln and ln.split('=')[0] in
                        ('SUBSYSTEM', 'SECTION0', 'STRAINSECTION0', 'GROUP0',
                         'STRING0.STRING', 'TOWER0', 'OBJECTMODELPOINTER')) else FG
        txt(d, (112, 396 + k * 34), ln, 17.5, col, a=ap, mono=True)

    # ---- 右下：这一级的属性 ----
    title, rows = CHAIN_ATTR[cur]
    panel(d, (1180, 348, 1830, 620), ap, fill=PANEL2, border=AMBER)
    txt(d, (1204, 360), '它的属性（BASEFAMILY → fam）', 18, AMBER, a=ap, bold=True)
    txt(d, (1204, 394), title, 15, MUTED, a=ap)
    for k, ln in enumerate(rows):
        txt(d, (1204, 428 + k * 30), ln, 14.5, FG, a=ap, mono=True)
    if not rows:
        txt(d, (1204, 428), '——', 15, MUTED, a=ap)

    if total <= len(lines):                      # 这份文件已经列全了
        txt(d, (112, 700), f'以上是全文，共 {total} 行', 14, GREEN, a=ap)

    # 面板下半：这一跳用哪个键、取到谁
    if hop_i is not None:
        aa = bp(t, dur, 0.10 + hop_i * 0.13 + 0.02)
        key = chain[hop_i][1]
        nxt = chain[hop_i + 1]
        txt(d, (112, 606), '这一跳', 15, MUTED, a=aa)
        txt(d, (186, 604), key, 17, AMBER, a=aa, mono=True, bold=True)
        txt(d, (186 + d.textlength(key, font=F('mono', 17)) + 20, 606),
            '取第一条  →  ' + ((nxt[2] + '….cbm') if nxt[2] else 'F1….cbm'),
            16, CYAN, a=aa, mono=True)
        txt(d, (112, 642), '计数键（GROUPS.NUM 等）决定"这条键有几条"，取哪一条不影响能不能走通',
            14.5, MUTED, a=aa)

    # ---- 底部：三种键的分工 ----
    a = bp(t, dur, 0.62)
    panel(d, (90, 786, 1830, 906), a, fill=PANEL2)
    keys = [('编号键', 'SECTIONn / STRAINn / GROUPn', '往下一级', CYAN),
            ('模型指针', 'OBJECTMODELPOINTER', '往物理模型', GREEN),
            ('属性指针', 'BASEFAMILY', '往属性文件', AMBER)]
    for k, (nm, kk, to, col) in enumerate(keys):
        aa = bp(t, dur, 0.66 + k * 0.04)
        x = 114 + k * 580
        txt(d, (x, 800), nm, 18, col, a=aa, bold=True)
        txt(d, (x, 834), kk, 15, FG, a=aa, mono=True)
        txt(d, (x, 866), to, 15, MUTED, a=aa)

    # ---- 右下：为什么能跳 ----
    a = bp(t, dur, 0.80)
    panel(d, (1180, 640, 1830, 762), a, fill=PANEL2)
    txt(d, (1204, 652), '为什么能跳', 19, CYAN, a=a, bold=True)
    for k, s_ in enumerate(['① 值就是文件名，不是 ID/URL',
                            '② 跳过去先读回 ENTITYNAME',
                            '③ 键名逐层换，判据不变']):
        txt(d, (1204, 688 + k * 30), s_, 16, FG, a=bp(t, dur, 0.84 + k * 0.03))


def draw_a9(d, t, dur):                                   # 三条边：层级 / 属性 / 模型
    # ---- 顶部：属性边（每一级 cbm 都可以挂一个 fam）----
    a = bp(t, dur, 0.02)
    panel(d, (150, 180, 1725, 224), a, fill=PANEL2, border=AMBER)
    txt(d, (168, 190), '属性边  BASEFAMILY → *.fam　每一级 cbm 都可以挂一个属性文件',
        18, AMBER, a=a, bold=True)
    txt(d, (1210, 192), 'line04：350 条 / 499 个 cbm', 14, MUTED, a=a)

    # ---- 上排：层级链（cbm → cbm）----
    top = [('工程', 'F1', 150), ('分段', 'F2', 480), ('耐张段', 'F3', 810),
           ('设备组', 'F4', 1140), ('部件', 'L5', 1470)]
    for i_, (nm, lv, x) in enumerate(top):
        a2 = bp(t, dur, 0.04 + i_ * 0.05)
        panel(d, (x, 244, x + 250, 334), a2)
        txt(d, (x + 16, 252), lv, 14, CYAN, a=a2, mono=True, bold=True)
        txt(d, (x + 16, 274), nm, 22, FG, a=a2, bold=True)
        txt(d, (x + 16, 306), '.cbm', 14, MUTED, a=bp(t, dur, 0.05 + i_ * 0.05), mono=True)
        aa = bp(t, dur, 0.10 + i_ * 0.05)
        if aa > 0:                                  # 向上接属性带
            d.line([x + 125, 244, x + 125, 244 - 20 * aa], fill=mix(BG, AMBER, aa), width=2)
    for i_ in range(4):
        aa = bp(t, dur, 0.08 + i_ * 0.05)
        x = top[i_][2] + 254
        arrow_h(d, x, x + 66, 292, aa, (100, 116, 139), thickness=3, head=10)
        txt(d, (x, 258), ['SECTION', 'STRAIN', 'GROUP', 'SUBDEV'][i_],
            11, MUTED, a=aa, mono=True)

    # ---- 模型边：只从设备组 / 部件向下 ----
    a = bp(t, dur, 0.34)
    d.line([1265, 334, 1265, 372], fill=mix(BG, (249, 115, 22), a), width=3)
    txt(d, (1282, 340), 'OBJECTMODELPOINTER', 14, (251, 146, 60), a=a, mono=True)
    a = bp(t, dur, 0.40)
    for k in range(6):
        d.line([1595, 336 + k * 7, 1595, 341 + k * 7], fill=mix(BG, (251, 146, 60), a), width=2)
    txt(d, (1282, 358), '设备组 / 部件两级才有；line04 的 343 条全在部件级',
        13, (251, 146, 60), a=a)

    bot = [('.dev', '物理模型 · 这是什么', 1140, GREEN, 0.42),
           ('.phm', '几何模型组', 1345, (56, 189, 248), 0.48),
           ('.mod / .stl', '几何本身', 1550, AMBER, 0.54)]
    for ext, nm, x, col, f0 in bot:
        aa = bp(t, dur, f0)
        panel(d, (x, 380, x + 175, 462), aa)
        d.rectangle([x, 380, x + 5, 462], fill=mix(BG, col, aa))
        txt(d, (x + 14, 388), ext, 18, col, a=aa, mono=True, bold=True)
        txt(d, (x + 14, 424), nm, 12.5, MUTED, a=bp(t, dur, f0 + 0.02))
        if x != 1550:
            aa2 = bp(t, dur, f0 + 0.06)
            arrow_h(d, x + 180, x + 200, 421, aa2, (100, 116, 139), thickness=2, head=7)
    txt(d, (1140, 470), 'dev --SOLIDMODELn--> phm --SOLIDMODELn--> mod / stl',
        12.5, MUTED, a=bp(t, dur, 0.60), mono=True)

    # ---- 左侧：三种边各自的数量 ----
    a = bp(t, dur, 0.30)
    txt(d, (150, 356), '三种边，三个方向', 21, CYAN, a=a, bold=True)
    nums = [('层级边', '779', 'cbm → 下一级 cbm', CYAN),
            ('属性边', '350', 'cbm → fam', AMBER),
            ('模型边', '343', 'cbm → dev → phm → 几何', GREEN)]
    for i_, (nm, n, d_, col) in enumerate(nums):
        aa = bp(t, dur, 0.36 + i_ * 0.07)
        y = 394 + i_ * 34
        txt(d, (150, y), nm, 17, col, a=aa, bold=True)
        txt(d, (238, y - 5), n, 25, col, a=aa, bold=True, mono=True)
        txt(d, (308, y), d_, 15, MUTED, a=aa, mono=True)

    # ---- 下：cbm / fam 样例 ----
    panel(d, (150, 540, 940, 756), bp(t, dur, 0.62))
    txt(d, (172, 552), '.cbm  键 = 值，行存储', 20, CYAN, a=bp(t, dur, 0.64), bold=True)
    cb = ["ENTITYNAME=F1System",
          "BASEFAMILY=7f9e83d7-754a-6475-….fam",
          "SECTIONS.NUM=2",
          "SECTION0=67849309-abd6-2868-….cbm",
          "SECTION1=e1024300-4be6-4d96-….cbm"]
    for i_, ln in enumerate(cb):
        txt(d, (172, 594 + i_ * 32), ln, 15.5, FG, a=bp(t, dur, 0.66 + i_ * 0.022), mono=True)

    panel(d, (980, 540, 1725, 756), bp(t, dur, 0.70))
    txt(d, (1002, 552), '.fam  属性名 = 关键字 = 值', 20, AMBER, a=bp(t, dur, 0.72), bold=True)
    fm = ["设计阶段工程名称=DESIGNPROJECTNAME=XX线Π接段500kV线路工程",
          "线路长度=LINELENGTH=0.100000",
          "杆塔基数=TOWERNUMBER=2",
          "部件生产厂家==国网金具库"]
    for i_, ln in enumerate(fm):
        txt(d, (1002, 594 + i_ * 32), ln, 13.5, FG if i_ < 3 else AMBER,
            a=bp(t, dur, 0.74 + i_ * 0.022), mono=True)

    a = bp(t, dur, 0.86)
    txt(d, (150, 786), '层级边搭骨架，属性边给每一级挂属性，模型边在设备组以下接几何 —— 三条边在同一个 cbm 里并存',
        20, FG, a=a)
    txt(d, (150, 822), 'line04：148 个设备组一个模型指针都没有，343 条全在部件级；350 条属性边里，148 个设备组也是空的',
        19, AMBER, a=bp(t, dur, 0.92))
    txt(d, (150, 858), '所以"cbm 指向 dev"必须限定层级：不是工程，是设备组与部件',
        19, MUTED, a=bp(t, dur, 0.96))


def draw_a10(d, t, dur):                                  # dev / phm / mod 全文
    a = bp(t, dur, 0.03)
    txt(d, (90, 186), '三个文件，全文照抄 —— 一个金具从「是什么」到「长什么样」',
        22, MUTED, a=a)

    # ---- dev 全文 ----
    a = bp(t, dur, 0.06)
    panel(d, (90, 224, 640, 470), a, fill=(13, 17, 23))
    d.rectangle([90, 224, 96, 470], fill=mix(BG, GREEN, a))
    txt(d, (112, 234), '.dev  全文 6 行', 17, GREEN, a=a, bold=True)
    dev = ["SYMBOLNAME=FITTINGS",
           "DEVICETYPE=FITTINGS",
           "BASEFAMILY=0033cb72-….fam",
           "SOLIDMODELS.NUM=1",
           "SOLIDMODEL0=da314472-….phm",
           "TRANSFORMMATRIX0=1,0,0,0,…（单位阵）"]
    for k, ln in enumerate(dev):
        txt(d, (112, 274 + k * 30), ln, 15, FG, a=a, mono=True)
    txt(d, (112, 444), '类型 + 属性 + 模型 + 位姿，就这些', 13.5, MUTED, a=a)

    # ---- phm 全文 ----
    a = bp(t, dur, 0.16)
    panel(d, (670, 224, 1180, 470), a, fill=(13, 17, 23))
    d.rectangle([670, 224, 676, 470], fill=mix(BG, (56, 189, 248), a))
    txt(d, (692, 234), '.phm  全文 4 行', 17, (56, 189, 248), a=a, bold=True)
    phm = ["SOLIDMODELS.NUM=1",
           "SOLIDMODEL0=56c251b6-….stl",
           "TRANSFORMMATRIX0=1,0,0,0,…（单位阵）",
           "COLOR0=215,215,215,100"]
    for k, ln in enumerate(phm):
        txt(d, (692, 274 + k * 30), ln, 15, FG, a=a, mono=True)
    txt(d, (692, 400), '这个金具只有 1 个零件，', 14, MUTED, a=a)
    txt(d, (692, 424), '颜色 215/215/215，不透明度 100', 14, MUTED, a=a)

    # ---- mod 全文 ----
    a = bp(t, dur, 0.28)
    panel(d, (1210, 224, 1830, 470), a, fill=(13, 17, 23))
    d.rectangle([1210, 224, 1216, 470], fill=mix(BG, AMBER, a))
    txt(d, (1232, 234), '.mod  全文 10 行（坐标已偏移脱敏）', 16, AMBER, a=a, bold=True)
    mod = ["CODE=30", "POINTNUM=4",
           "POINT1=1,27.7447,112.6482,53.300,13",
           "POINT2=2,27.7450,112.6492,53.300,13",
           "POINT3=3,27.7447,112.6482,59.300,42",
           "POINT4=4,27.7450,112.6492,59.300,42",
           "LINENUM=3", "LINE1=1,3", "LINE2=2,4", "LINE3=3,4"]
    for k, ln in enumerate(mod):
        txt(d, (1232, 268 + k * 19.5), ln, 13.5, FG, a=a, mono=True)

    # ---- 左下：五族 ----
    a = bp(t, dur, 0.48)
    panel(d, (90, 496, 1180, 700), a, fill=PANEL2)
    txt(d, (114, 510), '.mod 没有统一表头，按首行关键字分五族（line04 共 31 份）',
        19, CYAN, a=a, bold=True)
    fams = [('CODE=201/31/30', '12', '点 + 线'), ('CODE=1019', '4', '带参截面'),
            ('Bolt=', '8', '螺栓阵列'), ('TYPE=', '4', '型材'), ('HNum,', '3', '杆塔')]
    for k, (k_, n, d_) in enumerate(fams):
        aa = bp(t, dur, 0.52 + k * 0.04)
        x = 114 + k * 212
        txt(d, (x, 552), k_, 15, CYAN, a=aa, mono=True)
        txt(d, (x, 582), n, 26, AMBER, a=aa, bold=True, mono=True)
        txt(d, (x, 620), d_, 15, MUTED, a=aa)
    txt(d, (114, 664), '同一个扩展名，五种写法 —— 判型只看第一行，不能看后缀',
        17, FG, a=bp(t, dur, 0.70))

    # ---- 右下：stl ----
    a = bp(t, dur, 0.58)
    panel(d, (1210, 496, 1830, 700), a, border=CYAN)
    txt(d, (1234, 510), '.stl 有两种表达', 19, CYAN, a=a, bold=True)
    txt(d, (1234, 546), 'Binary：80 字节头 + 4 字节面片数 + 50 字节/面片', 15, FG, a=a)
    txt(d, (1234, 576), '文件大小 = 84 + 50 × n', 16, AMBER, a=bp(t, dur, 0.64), mono=True)
    txt(d, (1234, 610), '本样本 41 份全部整除，全为 Binary', 15, MUTED, a=bp(t, dur, 0.70))
    txt(d, (1234, 644), '这个 phm 指的就是一个 stl，不是 mod', 15, MUTED, a=bp(t, dur, 0.74))

    # ---- 结论 ----
    a = bp(t, dur, 0.80)
    txt(d, (90, 728), 'dev 回答"是什么"，phm 回答"由哪些零件组成"，mod / stl 回答"长什么样"',
        21, FG, a=a)
    txt(d, (90, 766), '三者都只是键值行文本，加起来 20 行；没有一个字节是二进制（stl 除外）',
        20, AMBER, a=bp(t, dur, 0.86))
    txt(d, (90, 802), '所以完全可以只用 type 命令读 —— 不需要建模软件，也不需要解析库',
        19, MUTED, a=bp(t, dur, 0.90))

    a = bp(t, dur, 0.92)
    panel(d, (90, 840, 1830, 964), a, fill=PANEL2)
    txt(d, (114, 856), 'line04 里这三类文件各有多少', 18, CYAN, a=a, bold=True)
    qa = [('dev', '197', '设备模板'), ('phm', '79', '零件组合'),
          ('mod + stl', '31 + 41', '几何本身')]
    for k, (k_, n, d_) in enumerate(qa):
        aa = bp(t, dur, 0.94 + k * 0.02)
        x = 114 + k * 580
        txt(d, (x, 892), k_, 16, MUTED, a=aa, mono=True)
        txt(d, (x + 110, 884), n, 26, FG, a=aa, bold=True, mono=True)
        txt(d, (x + 260, 892), d_, 15, MUTED, a=aa)


def draw_a12(d, t, dur):                                  # 实体 + 三指针
    ents = [('TOWER_DEVICE', '表 A.24', '塔身 / 串 / 基础', '141',
             'BASEFAMILY · 模型指针 · 矩阵'),
            ('WIRE', '表 A.26', '线体（导线、地线、跳线）', '138',
             'KVALUE · SPLIT · POINT.BLHA'),
            ('WIRE_DEVICE', '表 A.25', '间隔棒、防振锤', '48', 'BLHA · 变换矩阵'),
            ('CROSS', '表 A.27', '跨越物', '16', 'BASEFAMILY · 模型指针')]
    for i, (nm, tb, what, n, keys) in enumerate(ents):
        a = bp(t, dur, 0.04 + i * 0.08)
        x = 90 + i * 442
        panel(d, (x, 206, x + 412, 456), a)
        txt(d, (x + 22, 218), nm, 21, CYAN, a=a, mono=True, bold=True)
        txt(d, (x + 22, 254), tb, 16, MUTED, a=bp(t, dur, 0.05 + i * 0.08))
        txt(d, (x + 22, 284), what, 19, FG, a=bp(t, dur, 0.06 + i * 0.08))
        txt(d, (x + 22, 328), keys, 15, MUTED, a=bp(t, dur, 0.07 + i * 0.08), mono=True)
        txt(d, (x + 22, 382), n, 42, AMBER, a=bp(t, dur, 0.09 + i * 0.08),
            bold=True, mono=True)

    a = bp(t, dur, 0.42)
    txt(d, (90, 484), '141 个 TOWER_DEVICE 不是 141 基塔：塔身 6 + 绝缘子串 118 + 基础 17，靠 DEVICETYPE 区分',
        21, AMBER, a=a)
    txt(d, (90, 522), 'DEVICETYPE 只能取 11810.2 表 1 / 表 2：CONDUCTOR · GROUNDWIRE · OPGW · STRING · FITTINGS · TOWER · BASE …',
        18, MUTED, a=bp(t, dur, 0.50))

    ptr = [('Cbm → Cbm', '779', '层级边', '上级 cbm 的编号键', CYAN),
           ('OBJECTMODELPOINTER', '343', '模型指针', '部件 cbm → *.dev', GREEN),
           ('BASEFAMILY', '547', '属性指针', '350 个 cbm + 197 个 dev', AMBER)]
    for i, (nm, n, kind, desc, col) in enumerate(ptr):
        a = bp(t, dur, 0.58 + i * 0.09)
        x = 90 + i * 582
        panel(d, (x, 588, x + 560, 786), a, border=col)
        txt(d, (x + 24, 602), nm, 19, col, a=a, mono=True, bold=True)
        txt(d, (x + 24, 636), n, 52, col, a=a, bold=True, mono=True)
        txt(d, (x + 24, 706), kind, 19, FG, a=bp(t, dur, 0.60 + i * 0.09))
        txt(d, (x + 24, 742), desc, 17, MUTED, a=bp(t, dur, 0.61 + i * 0.09))

    a = bp(t, dur, 0.88)
    txt(d, (90, 822), 'BASEFAMILY 可以为空：F4 设备组的值就是空串，统计配对率必须先过滤。',
        20, MUTED, a=a)
    txt(d, (90, 864), '三种指针的值都是文件名或 GUID —— 判据只能看后缀，不能看键名。',
        21, FG, a=bp(t, dur, 0.94))


def draw_a13(d, t, dur):                                  # 树 vs 图
    txt(d, (90, 194), '树  tree', 23, GREEN, a=bp(t, dur, 0.03), bold=True)
    txt(d, (1040, 194), '图  directed graph', 23, AMBER, a=bp(t, dur, 0.05), bold=True)

    lv = [('L1', '工程', 'F1System', '× 1'), ('L2', '分段', 'F2System', '× 2'),
          ('L3', '耐张段', 'F3System', '× 4'), ('L4', '设备组', 'F4System', '× 148'),
          ('L5', '部件', 'TOWER_DEVICE…', '× 343')]
    for i, (t_, nm, ent, n) in enumerate(lv):
        a = bp(t, dur, 0.08 + i * 0.07)
        y = 236 + i * 108
        col = AMBER if i == 4 else CYAN
        panel(d, (150, y, 610, y + 78), a, fill=PANEL2, border=col)
        txt(d, (172, y + 8), t_, 16, col, a=a, mono=True, bold=True)
        txt(d, (232, y + 4), nm, 23, FG, a=a, bold=True)
        txt(d, (232, y + 42), ent, 13, MUTED, a=a, mono=True)
        txt(d, (512, y + 18), n, 21, col, a=a, bold=True, mono=True)
        if i < 4:
            d.line([379, y + 78, 379, y + 108],
                   fill=mix(BG, (100, 116, 139), a), width=3)

    a = bp(t, dur, 0.42)
    txt(d, (150, 800), '5 个层级、4 条边，每个节点入度 = 1', 21, GREEN, a=a, bold=True)

    pp = [('F4 塔组 #39', 'STRING7.STRING', 1080), ('导体组 · 左档', 'BACKSTRING', 1332),
          ('导体组 · 右档', 'FRONTSTRING', 1584)]
    for i, (nm, key, x) in enumerate(pp):
        a = bp(t, dur, 0.44 + i * 0.06)
        panel(d, (x, 232, x + 220, 326), a, border=AMBER)
        txt(d, (x + 14, 246), nm, 18, FG, a=a, bold=True)
        txt(d, (x + 14, 284), key, 13, AMBER, a=a, mono=True)
        d.line([x + 110, 326, x + 110, 408], fill=mix(BG, AMBER, a), width=3)

    a = bp(t, dur, 0.62)
    d.line([1190, 408, 1694, 408], fill=mix(BG, AMBER, a), width=3)
    d.line([1442, 408, 1442, 498], fill=mix(BG, AMBER, a), width=3)
    aa = bp(t, dur, 0.70)
    panel(d, (1316, 492, 1584, 628), aa, fill=(234, 88, 12), border=(249, 115, 22))
    txt(d, (1340, 506), 'TOWER_DEVICE', 20, (255, 255, 255), a=aa, bold=True)
    txt(d, (1340, 550), '绝缘子串 #7', 20, (255, 237, 213), a=aa)
    txt(d, (1340, 594), '入度 = 3', 17, (254, 215, 170), a=aa)

    a2 = bp(t, dur, 0.78)
    txt(d, (1040, 648), '99 个节点存在多父引用，全图多出 281 条边', 20, AMBER, a=a2, bold=True)
    txt(d, (1040, 686), '① 边界塔被两个耐张段共用（2 个 F4，+2 条）', 18, FG, a=bp(t, dur, 0.82))
    txt(d, (1040, 718), '② 绝缘子串被塔组与两侧导体组共引（94 个，入度 2~7，+276 条）', 18, FG, a=bp(t, dur, 0.86))
    txt(d, (1040, 750), '③ 跨越物横穿多个耐张段（3 个 CROSS，+3 条）', 18, FG, a=bp(t, dur, 0.90))

    a3 = bp(t, dur, 0.92)
    txt(d, (90, 848), '标准表 A.20 的样例里，GROUP55 与 GROUP56 指向同一个 GUID —— 双引用是标准示范过的写法。',
        20, CYAN, a=a3, bold=True)
    txt(d, (90, 890), '树表达层级，图表达引用。遍历要按 UUID 去重，统计要按边计。', 21, FG,
        a=bp(t, dur, 0.96))


def draw_a14(d, t, dur):                                  # 六样本 + 铁律
    txt(d, (90, 194), '六个工程，规模差 16 倍，骨架一模一样', 23, CYAN,
        a=bp(t, dur, 0.03), bold=True)
    rows = [('line01', '500kV', '双回改接', '5.65 MB', '12,372', '1,072'),
            ('line02', '500kV', '单回', '10.80 MB', '22,640', '2,405'),
            ('line03', '500kV', '双回合并', '7.31 MB', '18,533', '1,964'),
            ('line04', '500kV', 'π 接短段', '1.44 MB', '1,394', '148'),
            ('line05', '500kV', '单双回混', '8.67 MB', '15,480', '1,226'),
            ('line06', '220kV', '单回 ×2', '2.44 MB', '2,508', '222')]
    for i, r in enumerate(rows):
        a = bp(t, dur, 0.06 + i * 0.045)
        y = 232 + i * 52
        hot = r[0] == 'line04'
        panel(d, (90, y, 980, y + 44), a,
              fill=(30, 58, 138) if hot else PANEL2,
              border=AMBER if hot else BORDER, radius=6)
        for k, (v, xx) in enumerate(zip(r, [108, 216, 296, 452, 634, 830])):
            txt(d, (xx, y + 10), v, 17, FG if k == 0 else MUTED, a=a,
                mono=(k in (0, 3, 4, 5)), bold=(k == 0))

    a = bp(t, dur, 0.40)
    txt(d, (90, 566), '全部 GIMPKGT · 全部 784 字节头 · 全部 QGDW2/2023 · 五级骨架与挂接键零差异',
        20, GREEN, a=a, bold=True)

    txt(d, (1040, 194), '标准怎么写，文件怎么填', 23, AMBER, a=bp(t, dur, 0.46), bold=True)
    rows2 = [('工况元组', '标准 4 维，五份只写 3 维', '只有 line03 合规'),
             ('线路长度', 'line03 填 0；line04 差 4 倍', '必须几何重建'),
             ('回路数', '枚举：0 单回 / 1 双回', '按"几回"读就错'),
             ('杆塔基数', 'line04 分段各 1，实测 6 塔', '口径待确认')]
    for i, (k, v, r) in enumerate(rows2):
        a = bp(t, dur, 0.50 + i * 0.070)
        y = 232 + i * 78
        panel(d, (1040, y, 1830, y + 66), a, fill=PANEL2)
        txt(d, (1060, y + 8), k, 18, CYAN, a=a, bold=True)
        txt(d, (1060, y + 36), v, 16, FG, a=a)
        txt(d, (1580, y + 22), r, 16, AMBER, a=bp(t, dur, 0.53 + i * 0.070), bold=True)

    a = bp(t, dur, 0.80)
    txt(d, (90, 632), '五条读法', 24, CYAN, a=a, bold=True)
    laws = ['头按字段读 —— 784 是十一个字段之和，不是"魔数 + 768 + 8"',
            '层级认 ENTITYNAME —— 标准大写、实例驼峰，比较一律 upper()',
            '子文件认值后缀 —— 以 .cbm 结尾且键不带 .NUM，才是下一级',
            'UUID 先去重 —— 同一文件只入队一次，边单独计',
            '属性走指针、长度走几何 —— BASEFAMILY 找属性，BLHA 重算长度']
    for i, s_ in enumerate(laws):
        aa = bp(t, dur, 0.74 + i * 0.028)
        y = 678 + i * 44
        txt(d, (90, y), f'0{i + 1}', 17, AMBER, a=aa, mono=True, bold=True)
        txt(d, (138, y), s_, 19, FG, a=aa)

    a2 = bp(t, dur, 0.80)
    txt(d, (1040, 540), '配套：tutorial.py 十步 · tutorial.ipynb 交互版', 17, (170, 184, 204), a=a2)
    txt(d, (1040, 572), '下一期：变电篇 —— 同一套标准，另一半世界', 17, AMBER, a=a2)

    # 结论的边界：样本同源，不能外推成"所有实现都这样"
    a3 = bp(t, dur, 0.86)
    panel(d, (1040, 620, 1820, 754), a3, fill=(30, 41, 59), border=(217, 119, 6))
    txt(d, (1062, 634), '结论的边界', 19, AMBER, a=a3, bold=True)
    txt(d, (1062, 666), '六份里五份由道亨 SLW3D 导出（line03 不同）', 17, FG,
        a=bp(t, dur, 0.88))
    txt(d, (1062, 696), '这些"一致"首先是该导出端的一致性，', 17, FG,
        a=bp(t, dur, 0.90))
    txt(d, (1062, 726), '不等于所有 GIM 实现的普遍规律。', 17, (226, 232, 240),
        a=bp(t, dur, 0.92))


# ---------------------------------------------------------------- 终端实录
# 每一跳都对着 line04 的真实文件；输出行是 `type` / `findstr` 的真实结果（仅脱敏设计院名与工程名）
LIVE_BEATS = [
    {'p': r'D:/gim>', 'cmd': 'dir line04.gim', 'note': '第 1 步 · 看包有多大',
     'out': [('2026-07-16  15:04         1,439,639 line04.gim', 'out')]},

    {'p': r'D:/gim>', 'cmd': 'python tutorial.py "" line04.gim --step=1',
     'note': '第 2 步 · 按字段读头',
     'out': [('Step 1  容器头：784 字节 = 表 A.1 十一个定长字段之和', 'dim'),
             ('文件 line04.gim   1,439,639 字节', 'out'),
             ('字段', '偏移', '字节', '值', 'head'),
             ('文件标识', '0', '16', 'GIMPKGT', 'row'),
             ('文件名称', '16', '256', 'XX线Π接段.gim', 'row'),
             ('编辑者', '272', '64', '某省电力设计院', 'row'),
             ('编辑单位', '336', '256', '北京道亨软件股份有限公司', 'row'),
             ('软件名称', '592', '128', 'SLW3D 送电线路设计系统 7.0', 'row'),
             ('创建时间', '720', '16', '2026-07-16 15:04', 'row'),
             ('主版本号', '736', '8', '7', 'row'),
             ('次版本号', '744', '8', '0', 'row'),
             ('修订号', '752', '8', 'QGDW2', 'row'),
             ('构建号', '760', '8', '2023', 'row'),
             ('存储域大小', '768', '16', '1438855', 'keyrow'),
             ('784 + 1,438,855 = 1,439,639  =  文件大小   [OK]', 'ok'),
             ('784 处是 7z 签名，后面全是压缩内容   [OK]', 'ok')]},

    {'p': r'D:/gim>', 'cmd': 'cd line04', 'note': '第 3 步 · 进解包目录', 'out': []},

    {'p': r'D:/gim/line04>', 'cmd': 'dir /b', 'note': '第 3 步 · 四个目录',
     'out': [('Cbm', 'out'), ('Dev', 'out'), ('Phm', 'out'), ('Mod', 'out')]},

    {'p': r'D:/gim/line04>', 'cmd': 'cd Cbm', 'note': '第 4 步 · 打开根文件', 'out': []},

    {'p': r'D:/gim/line04/Cbm>', 'cmd': 'type project.cbm', 'note': '第 4 步 · 整个文件只有一行',
     'out': [('SUBSYSTEM=7f9e83d7-754a-6475-a59a-d2c96655fdfb.cbm', 'key')]},

    {'p': r'D:/gim/line04/Cbm>', 'cmd': 'type 7f9e83d7-754a-6475-a59a-d2c96655fdfb.cbm',
     'note': '第 5 步 · 第一级：工程',
     'out': [('ENTITYNAME=F1System', 'out'),
             ('BASEFAMILY=7f9e83d7-754a-6475-a59a-d2c96655fdfb.fam', 'out'),
             ('SECTIONS.NUM=2', 'out'),
             ('SECTION0=67849309-abd6-2868-a678-76d8bfc97bff.cbm', 'key'),
             ('SECTION1=e1024300-4be6-4d96-b86d-0d1b2a5591df.cbm', 'out'),
             ('MATERIALSHEET=', 'out')]},

    {'p': r'D:/gim/line04/Cbm>', 'cmd': 'type 67849309-abd6-2868-a678-76d8bfc97bff.cbm',
     'note': '第 6 步 · 第二级：分段',
     'out': [('ENTITYNAME=F2System', 'out'),
             ('BASEFAMILY=67849309-abd6-2868-a678-76d8bfc97bff.fam', 'out'),
             ('STRAINSECTIONS.NUM=2', 'out'),
             ('STRAINSECTION0=9686e776-7338-6d50-bf87-d28cfb6dcb4b.cbm', 'key'),
             ('STRAINSECTION1=f18271f9-58ae-4c82-9c73-61f83254964b.cbm', 'out'),
             ('MATERIALSHEET=', 'out')]},

    {'p': r'D:/gim/line04/Cbm>',
     'cmd': 'findstr /b "GROUPS.NUM GROUP0" 9686e776-7338-6d50-bf87-d28cfb6dcb4b.cbm',
     'note': '第 7 步 · 第三级：耐张段（11 个组）',
     'out': [('GROUPS.NUM=11', 'out'),
             ('GROUP0=f3a5338a-4d81-4747-874f-ed14849251b9.cbm', 'key')]},

    {'p': r'D:/gim/line04/Cbm>',
     'cmd': 'findstr /b "GROUPTYPE BLHA STRINGS.NUM STRING7.STRING" '
            'f3a5338a-4d81-4747-874f-ed14849251b9.cbm',
     'note': '第 8 步 · 第四级：塔组（16 串）',
     'out': [('GROUPTYPE=TOWER', 'out'),
             ('BLHA=27.745227,112.648678,60.000,433.75（已偏移脱敏）', 'out'),
             ('STRINGS.NUM=16', 'out'),
             ('STRING7.STRING=6d8b6745-1146-41db-9050-6e37d65052f3.cbm', 'key')]},

    {'p': r'D:/gim/line04/Cbm>',
     'cmd': 'findstr /b "OBJECTMODELPOINTER BASEFAMILY ENTITYNAME" '
            '6d8b6745-1146-41db-9050-6e37d65052f3.cbm',
     'note': '第 9 步 · 第五级：部件（绝缘子串）',
     'out': [('OBJECTMODELPOINTER=f203c239-4938-4231-bf9a-9c60727e724e.dev', 'key'),
             ('BASEFAMILY=6d8b6745-1146-41db-9050-6e37d65052f3.fam', 'out'),
             ('ENTITYNAME=Tower_Device', 'out')]},

    {'p': r'D:/gim/line04/Cbm>',
     'cmd': r'findstr /b "DEVICETYPE SYMBOLNAME" ..\Dev\f203c239-4938-4231-bf9a-9c60727e724e.dev',
     'note': '第 10 步 · 类型在 dev 里，不在 cbm 里',
     'out': [('DEVICETYPE=STRING', 'key'),
             ('SYMBOLNAME=INSULATOR', 'out')]},

    {'p': r'D:/gim/line04/Cbm>',
     'cmd': r'findstr /b "绝缘子型号 串类型 总长度" ..\Dev\f203c239-4938-4231-bf9a-9c60727e724e.fam',
     'note': '第 11 步 · 属性在 fam 里：就是这一串',
     'out': [('绝缘子型号=INSULATORTYPE=U300B/195', 'key'),
             ('串类型=SETTYPE=耐张串', 'out'),
             ('总长度=LENGTH=8.685390', 'out')]},
]

LIVE_COL = {'out': (203, 213, 225), 'dim': (120, 136, 159),
            'key': AMBER, 'ok': GREEN}


def draw_live(d, t, dur):                                 # 终端实录：完整走一条链
    x0, y0, x1, y1 = 110, 186, 1810, 962
    panel(d, (x0, y0, x1, y1), 1.0, fill=(13, 17, 23), border=(51, 65, 85), radius=12)

    # 标题栏
    d.rounded_rectangle([x0, y0, x1, y0 + 44], 12, fill=mix(BG, (23, 30, 44), 1))
    d.rectangle([x0, y0 + 30, x1, y0 + 44], fill=mix(BG, (23, 30, 44), 1))
    for i, c in enumerate([(248, 113, 113), (251, 191, 36), (52, 211, 153)]):
        d.ellipse([x0 + 20 + i * 22, y0 + 15, x0 + 32 + i * 22, y0 + 27],
                  fill=mix(BG, c, 1))
    txt(d, (x0 + 100, y0 + 12), '命令提示符 — line04（真实样本，未打开任何建模软件）',
        16, MUTED)
    d.line([x0, y0 + 44, x1, y0 + 44], fill=mix(BG, (51, 65, 85), 1), width=2)

    LHH, FS = 29, 20
    body_top, body_bot = y0 + 58, y1 - 54
    rows = (body_bot - body_top) // LHH

    # 时间表：按内容长度分配
    weights = [0.8 + len(b['cmd']) * 0.020 + len(b['out']) * 0.50 for b in LIVE_BEATS]
    scale = (dur * 0.94) / sum(weights)

    records = []          # (prompt, text, color)
    cursor = False
    cur_note, cur_step = LIVE_BEATS[0]['note'], 1
    acc = 0.0
    for i, b in enumerate(LIVE_BEATS):
        w = weights[i] * scale
        type_s = min(len(b['cmd']) * 0.020 * scale, w * 0.55)
        start = acc
        if t < start:
            break
        cur_note, cur_step = b['note'], i + 1
        # 打字
        if t < start + type_s:
            n = int(len(b['cmd']) * (t - start) / max(type_s, 1e-6))
            records.append((b['p'], b['cmd'][:n], FG))
            cursor = True
            acc = start + w
            break
        records.append((b['p'], b['cmd'], FG))
        # 输出逐行
        k = int((t - start - type_s) / max(0.12, w * 0.02)) if b['out'] else 0
        k = min(k, len(b['out']))
        for row in b['out'][:k]:
            if len(row) == 5:                    # 表头 / 字段行：固定列位
                kind = 'key' if row[4] == 'keyrow' else 'out'
                records.append(('', row, LIVE_COL.get('key' if kind == 'key' else 'out')
                                if row[4] != 'head' else (100, 116, 139)))
            else:
                records.append(('', row[0], LIVE_COL[row[1]]))
        cursor = False
        if i + 1 < len(LIVE_BEATS):
            records.append(('', '', None))
        acc = start + w
        if t < acc:
            break

    vis = records[-rows:]
    # 内容超过一屏时底对齐（跟真实终端滚动一致），没超过则从顶部长下来
    y_start = body_top if len(records) < rows else body_bot - len(vis) * LHH + 6
    for i, (p_, c_, col) in enumerate(vis):
        y = y_start + i * LHH
        if not c_ and col is None:              # 段间空行
            continue
        if isinstance(c_, tuple):               # 表行：label + 三列固定位置
            lab, off, ln, val = c_[:4]
            txt(d, (x0 + 40, y), lab, FS, col)
            txt(d, (x0 + 300, y), off, FS, col, mono=True)
            txt(d, (x0 + 400, y), ln, FS, col, mono=True)
            txt(d, (x0 + 500, y), val, 19, col)
        elif p_:
            wpx = txt(d, (x0 + 30, y), p_, FS, (74, 222, 128), mono=True)
            txt(d, (x0 + 30 + wpx, y), c_, FS, col, mono=True)
        else:
            txt(d, (x0 + 30, y), c_, FS, col, mono=True)

    # 光标
    if cursor:
        p_, c_, _ = records[-1]
        f = F('mono', FS)
        off = d.textlength(p_, font=f) + d.textlength(c_, font=f)
        if (t * 2) % 1 < 0.55:
            d.rectangle([x0 + 30 + off + 3, body_top + (len(vis) - 1) * LHH + 4,
                         x0 + 30 + off + 14, body_top + (len(vis) - 1) * LHH + 24],
                        fill=mix(BG, FG, 0.85))

    # 状态栏
    d.line([x0, y1 - 54, x1, y1 - 54], fill=mix(BG, (51, 65, 85), 1), width=2)
    txt(d, (x0 + 30, y1 - 38), cur_note, 17, AMBER, bold=True)
    txt(d, (x1 - 330, y1 - 38), 'line04 · 499 个 cbm', 16, MUTED)


# ---------------------------------------------------------------- 分镜定义
SEGS = [
    # ---------------- 序 ----------------
    {'title': '一条 .gim 里，装了什么', 'draw': draw_a1, 'ch': 0,
     'narr': '从零开始学国网 GIM 标准，第一期。一个 GIM 文件里到底装了什么？这个问题看着简单，但要答准，得同时翻三本标准：一本管数据怎么存，一本管模型怎么建，一本管设计怎么用。我们拿一条真实线路的交付件，从第一个字节开始，一直拆到一根角钢。这一集分五步：先看容器，再看层级，然后是六种文件格式，接着是设备与指针，最后拿六个工程互相比较。'},

    # ---------------- 第 1 章 容器 ----------------
    {'title': '第 1 章 容器', 'draw': make_ch(0), 'ch': 1, 'plain': True,
     'narr': '先看容器：一个文件，怎么把整个工程装进去。七百八十四字节的头，十一个定长字段，四个目录。'},
    {'title': '784 字节：标准表 A.1 的十一个字段', 'draw': draw_a2, 'ch': 1,
     'narr': '第一层是容器。前面七百八十四字节是文件头。这个数不是经验值——翻开交互规范附录 A 的表 A 点一，文件头是十一个定长字段：文件标识十六字节、文件名称二百五十六、编辑者六十四、编辑单位二百五十六、软件名称一百二十八、创建时间十六，再加四个八字节的版本号，最后是十六字节的存储域大小。加起来正好七百八十四。所以读头不用猜，按占位长度一段一段切就行。存储域大小这个字段记录压缩域有多少字节，解包时按它定位，不用去扫文件尾。有一点要提醒：字段值以零字节结尾，空字段不留痕迹；按非空段数下标，遇到多一个设计单位段的包就会错位。'},
    {'title': '四个目录，各管一件事', 'draw': draw_s2, 'ch': 1,
     'narr': '解包之前先读头：确认文件标识是 GIMPKGT，标准版本是 QGDW2 二零二三，再往下拆。头后面是四个目录，这是标准规定的存储域：C B M、D E V、P H M、M O D，目录名固定，里面放什么文件也固定。C B M 放组装模型，引用物理模型和本层属性，负责把层级串起来；D E V 放物理模型，引用几何模型组与属性，回答这是什么；P H M 是几何模型组，把模型拆成零件；M O D 放几何本身，m o d 是参数化几何，s t l 是非参数化三角面片。口诀还是那句：Cbm 管谁挂在谁下面，Dev 管这是什么，Phm 管由哪些零件组成，Mod 管长什么样、在哪。要分清标准和实例：标准只规定四个目录和每类文件的职责，不规定数量。本样本四个目录合计一千三百九十四个文件、十三点八兆；换个工程这些数字全变，但目录和文件类型的职责不变。'},

    # ---------------- 第 2 章 层级 ----------------
    {'title': '第 2 章 层级', 'draw': make_ch(1), 'ch': 2, 'plain': True,
     'narr': '再看层级：标准把一条线路拆成五级，工程、分段、耐张段、设备、部件，一级一级往下走。'},
    {'title': '标准只写了五级：工程到部件', 'draw': draw_a4, 'ch': 2,
     'narr': '第二层是层级。交互规范第七点二条写得很干脆：线路工程按工程、分段、耐张段、设备、部件，分五级。前三级有属性表：工程级四十三个属性，分段级三十七个，耐张段十四个；设备级和部件级不在这里定，交给建模规范的附录 B。这里有个最常见的误读：第二级是分段，不是回路。一条线路可以按标段、按架设方式、按改接范围切段，一个分段里也可以有多回。line06 一棵 F1 挂两条运行线路，那是两个分段。'},
    {'title': '从 1 到 343：五级怎么裂开', 'draw': draw_a5, 'ch': 2,
     'narr': '五级落到文件上，每一级都是一个独立的 c b m。line04 实测：一个根文件、一个工程级、两个分段、四个耐张段、一百四十八个设备组、三百四十三个部件，加起来正好四百九十九个，一个不多一个不少。数量是怎么裂开的？工程到分段乘二，分段到耐张段乘二，耐张段到设备组乘三十七——跳得最狠的一段。但要说清楚：设备组的个数不是标准定死的常数，也不是为了凑数。它等于这个耐张段里实际有多少基塔、多少档导线、多少处跨越。以 line04 为例，一类耐张段是两基塔、八个导体组、一处跨越，一共十一组；另一类是两基塔、六十一个导体组、一处跨越，一共六十四组。设备组到部件只乘二点三，一基塔平均挂两三个部件。'},
    {'title': '每级一把钥匙', 'draw': draw_a6, 'ch': 2,
     'narr': '每一级往下走，用的键都不一样：根到一级是 SUBSYSTEM，一级到二级是 SECTION 加 SECTIONS 点 NUM，二级到三级是 STRAINSECTION，三级到四级是 GROUP。到了第四级还要按 GROUPTYPE 分三种走法：塔组用 TOWER、STRING、BASE 三组键，导体组和通道地物组用 SUBDEVICE。三个容易读错的地方：第一，NUM 必填，数量为零也要输出，所以有键无值不等于没这个键；第二，第四级有三套键；第三，塔组的 BASEFAMILY 标准写明是空值，拿它去找属性表必然落空。'},
    {'title': '下钻：每走一步，两道证明', 'draw': draw_a7, 'ch': 2,
     'narr': '下钻这件事，代码只有二十行，但每走一步要给两道证明。第一道，计数键说这层有几条边，用它定循环次数，不靠猜；第二道，读回子文件，ENTITYNAME 必须是这一级，才确认自己站对了。以 line04 这个工程为例：它是一个工程、两个分段，每个分段下两个耐张段，一共四个耐张段；这四个耐张段再挂出 150 条 GROUP 引用，去重后是 148 个设备组。这一遍走下来，断言一次都没落空。这里最容易错的一步是：SUBSYSTEM 的值是字符串，不是对象，必须先打开文件才能读出键——这一步错，后面全错。'},
    {'title': '主链跳转：值就是下一个文件名', 'draw': draw_s8, 'ch': 2,
     'narr': '主链跳转更直观：SUBSYSTEM 的值不是 I D 也不是 U R L，就是同目录里的下一个文件名。左边这一栏是每一跳落地的那个文件的全文：工程级六行，分段级六行，耐张段十五行，设备组四十行，部件四行——同一套写法，键名一级一级换，SECTIONS、STRAINSECTIONS、GROUPS、STRINGS。右边这一栏是它的属性文件：工程级有工程名和杆塔基数，分段级有电压等级和回路数，耐张段级有导线型号和代表档距；到了设备组，属性是空的——标准允许，塔组的位置写在 BLHA 里。所以每跳一次要顺手带走两样东西：下一级是谁，这一级什么属性。'},

    # ---------------- 第 3 章 格式 ----------------
    {'title': '第 3 章 格式', 'draw': make_ch(2), 'ch': 3, 'plain': True,
     'narr': '然后是格式：六种文件，排成一条单向引用链，越往下越具体。'},
    {'title': '六种格式，两条引用链', 'draw': draw_a9, 'ch': 3,
     'narr': '第三章讲格式。六种文件之间其实有三种边，方向各不相同。第一种是层级边：c b m 连下一级 c b m，工程、分段、耐张段、设备组、部件，line04 一共七百七十九条。第二种是属性边：每一个 c b m 都可以用 BASEFAMILY 挂一个 fam 属性文件，line04 里是三百五十条，还有一百四十九个 c b m 是空的。第三种是模型边：OBJECTMODELPOINTER 指向 d e v，d e v 再指向 p h m，p h m 指向 m o d 或 s t l。这里要盯住层级：标准在设备级和部件级都给了这个键，但 line04 的 148 个设备组一个都没填，三百四十三条全在部件级。所以“c b m 指向 d e v”这句话必须限定层级，不是工程级。c b m 是键等于值的行存储，第一行说明我是第几级，第二行指向属性文件，后面几行说我有几个下级。fam 是三段式：中文名、英文关键字、值。注意最后一行，部件生产厂家，中间空着，就是关键字为空——标准允许，所以切分只能切两刀。配对只看指针，不看文件名：line03 的 d e v 和 fam 完全异名，靠指针照样全部可达。'},
    {'title': 'dev 与 phm，mod 与 stl', 'draw': draw_a10, 'ch': 3,
     'narr': '这一段把三个文件全文摊开，不是节选。d e v 六行：SYMBOLNAME 和 DEVICETYPE 都是 FITTINGS，BASEFAMILY 指向属性文件，SOLIDMODELS 只有一条，指向一个 p h m，再加一条单位变换矩阵。p h m 四行：这个金具只有一个零件，是个 s t l，颜色 215，不透明度 100。m o d 十行：四个点、三条线，坐标我已经整体偏移脱敏。三个文件加起来二十行，全是键值文本。m o d 最容易踩坑，同一个扩展名下五种写法，判型只看第一行：CODE 开头是点线，Bolt 是螺栓，TYPE 是地线，HNum 是塔身。s t l 有二进制和 A S C I I 两种表达，本样本四十一份实测全是二进制；八十四加五十乘面片数，能整除就是二进制。'},
    {'title': 'walk 一遍：499 个节点，779 条边', 'draw': draw_s7, 'ch': 3,
     'narr': '更泛化的走法是递归 walk：不写死每层键名，只认一个判据——值以点 c b m 结尾、且键不带 NUM，就是子指针；没有子指针的就是叶子。line04 从头走一遍：一个工程，两条分段，四个耐张段，一百四十八个设备组，三百四十三个部件，一路走下来四百九十九个节点全部可达，零孤儿，引用边七百七十九条。叶子普查就是这段代码的运行结果：塔类一百四十一，导线一百三十八，附件四十八，跨越十六。这里要记四个词：工程层级是逻辑，文件引用是指针，唯一节点要去重，引用边是关系。边比节点多，说明有文件被多个父节点同时引用——下一章专门讲这个。'},

    # ---------------- 第 4 章 实体 ----------------
    {'title': '第 4 章 设备', 'draw': make_ch(3), 'ch': 4, 'plain': True,
     'narr': '第 4 章，设备。走到第五级，最小的单元是谁。四类设备，三种指针。'},
    {'title': '第 5 级只有四个名字', 'draw': draw_a12, 'ch': 4,
     'narr': '第五级只有四个名字：TOWER_DEVICE、WIRE、WIRE_DEVICE、CROSS，每个都有标准规定的最小键集，缺键就是不合规。塔类一百四十一个不是一百四十一基塔，它包含塔身六、绝缘子串一百一十八、基础十七，靠 DEVICETYPE 区分。把四个目录缝起来的是三种指针：层级边七百七十九条，模型指针三百四十三条，属性指针五百四十七条——三百五十个 c b m 加一百九十七个 d e v。三种指针的值都一样，都是文件名或 GUID，判据只能看后缀，不能看键名。'},
    {'title': '同一批文件：树看层级，图看引用', 'draw': draw_a13, 'ch': 4,
     'narr': '到这里可以回答一个问题：这到底是不是一棵树？左边是应该长的样子：工程、分段、耐张段、设备组、部件，五个层级四条边，每个节点只有一个父亲。右边是实际被画成的样子：同一个绝缘子串，塔组用 STRING 引它一次，左档用 BACKSTRING、右档用 FRONTSTRING 各引一次，它就有了三个父亲；回路多的串被引更多次。全图九十九个节点存在多父引用，入度从二到七，多出二百八十一条边：边界塔多两条，绝缘子串多二百七十六条，跨越物多三条。标准表 A 点二十的样例里，GROUP 五十五和 GROUP 五十六指向同一个 GUID——双引用是标准示范过的写法，不是厂商的 bug。'},

    # ---------------- 第 5 章 校验 ----------------
    {'title': '实操：从 .gim 到一根绝缘子串，全程只用终端', 'draw': draw_live, 'ch': 4,
     'narr': '好，前面都是看图。这一段我们动手，从原包一直走到一根绝缘子串，全程只用终端，不打开任何建模软件。'
             '先看这个包：一点四四兆。用配套脚本读头，十一个字段一条条列出来——文件标识 GIMPKGT，软件名 SLW3D，'
             '最后一行存储域大小 1438855。784 加它正好等于文件大小，一分不差；784 处就是 7z 的签名，后面全是压缩内容。'
             '解包之后是四个目录。进 Cbm，先打开 project.cbm——整个文件只有一行：SUBSYSTEM 指向另一个 cbm。'
             '它不知道这个工程有多少塔，只知道第一级是谁。'
             '顺着这个值打开：F1System，SECTIONS 点 NUM 等于 2，取第一条 SECTION。再到 F2、F3：'
             'F3 的 GROUPS 点 NUM 是 11，也就是这个耐张段挂十一个设备组。'
             '取 GROUP0，是一个 F4 塔组：GROUPTYPE 等于 TOWER，BLHA 是它的坐标，下面十六条挂点，'
             '挂的就是这个塔上的十六串绝缘子。取第七条，也就是第七串。'
             '打开它：只有三行。ENTITYNAME 写的是 TOWER DEVICE，一个模型指针，一个属性指针。'
             '注意，这里没有 DEVICETYPE，类型不在 c b m 里。跟着模型指针进 d e v 文件：DEVICETYPE 是 STRING，SYMBOLNAME 是 INSULATOR。'
             '再看属性文件：绝缘子型号 U300B 斜杠 195，串类型是耐张串，总长八点六八五米。'
             '从一点四四兆的压缩包，到一根具体的绝缘子串，八次打开文件，五级一跳不落，没有一次靠猜——'
             '每次都是读一个键、拿一个文件名、打开它。'},

    {'title': '第 5 章 规范', 'draw': make_ch(4), 'ch': 5, 'plain': True,
     'narr': '第 5 章，规范。六个工程摆在一起，看标准怎么写、文件怎么填。'},
    {'title': '六个工程并排看，五条读法', 'draw': draw_a14, 'ch': 5,
     'narr': '最后把六个工程摆在一起比一比。六份包，五百千伏五份、二百二十千伏一份，最小的一点四四兆、最大十点八兆，解包文件从一千三百九十四到两万两千六百四十，差十几倍；但容器、五级骨架、挂接键全部一样。要说清这一点：其中五份由道亨 SLW3D 导出，所以这些一致首先是这个导出端在六份样本之间的一致，不等于所有 GIM 实现的普遍规律。不稳的只有数量、值格式和个别字段：耐张段工况标准是四维，五份只写了三维，只有 line03 合规；线路长度 line03 填零、line04 差四倍多；回路数是枚举，零单回一双回，不是几回；杆塔基数 line04 两个分段各填一，包里却有六基塔。标准这么写，文件这么填，差异就摆在这里。五条读法收个尾：头按字段读、层级认 ENTITYNAME、子文件认值后缀、UUID 先去重、属性走指针长度走几何。配套脚本十步，填上路径就能跑。下一期，我们把这套方法用到变电工程上。'},
]

# ---------------------------------------------------------------- TTS（复用缓存）
def tts_get(seg_i):
    d = os.path.join(WORK, 'tts_edge')
    os.makedirs(d, exist_ok=True)
    # 按讲稿文本 + 版本哈希命名：改稿后旧音频自动失效，不会读到上一版
    h = hashlib.md5((SEGS[seg_i]['narr'] + '@' + TAG).encode('utf-8')).hexdigest()[:8]
    mp3 = os.path.join(d, f'{TAG}seg{seg_i + 1:02d}_{h}.mp3')
    if os.path.exists(mp3) and os.path.getsize(mp3) > 1000:
        return mp3
    try:
        import edge_tts
        import asyncio

        async def _gen():
            # GIM 读作 /giːm/（geem），不能逐字母念 G-I-M；
            # 但 GIMPKGT 是文件标识，要逐字母念，先保护起来再替换
            text = SEGS[seg_i]['narr'].replace('GIMPKGT', 'G I M P K G T')
            text = text.replace('GIM', 'geem')
            com = edge_tts.Communicate(text,
                                       'zh-CN-YunxiNeural', rate='+4%')
            await com.save(mp3)
        asyncio.new_event_loop().run_until_complete(_gen())
        return mp3
    except Exception as e:
        print(f'  TTS edge failed seg{seg_i + 1:02d}: {e}')
        raise


def dur_of(path):
    r = subprocess.run([FFPROBE, '-v', 'quiet', '-print_format', 'json',
                        '-show_format', path], capture_output=True, text=True)
    return float(json.loads(r.stdout)['format']['duration'])


# ---------------------------------------------------------------- 渲染与编码
def render_segment(seg_i, aud, max_dur=None, out=None):
    from PIL import Image, ImageDraw
    dur = dur_of(aud) + TAIL
    if max_dur:
        dur = min(dur, max_dur)
    n_frames = int(dur * FPS)
    if not out:
        out = os.path.join(WORK, f'{TAG}seg{seg_i + 1:02d}.mp4')
    # 只编码视频轨：音轨在 assemble() 里按“视频精确时长”逐段补静音后
    # 一次性拼成一整条。若在这里带上音轨，concat -c copy 会丢掉每段末尾的
    # 静音（0.7s），音频逐段前移 → 90s 处就差 1.2s（v5 实际发生）
    cmd = [FFMPEG, '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
           '-c:v', 'libx264', '-preset', 'fast',
           '-pix_fmt', 'yuv420p', '-an', out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for f in range(n_frames):
        t = f / FPS
        img = Image.new('RGB', (W, H), BG)
        CUR_IMG[0] = img
        d = ImageDraw.Draw(img)
        SEGS[seg_i]['draw'](d, t, dur)
        chrome(d, seg_i, t, dur)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()
    return out, dur


def video_dur(path):
    """视频轨精确时长：优先 nb_frames / FPS（无累积误差）。"""
    r = subprocess.run([FFPROBE, '-v', 'error', '-select_streams', 'v:0',
                        '-show_entries', 'stream=nb_frames,duration',
                        '-of', 'json', path], capture_output=True, text=True)
    st = (json.loads(r.stdout).get('streams') or [{}])[0]
    if st.get('nb_frames'):
        return int(st['nb_frames']) / FPS
    return float(st.get('duration') or dur_of(path))


def build_audio(seg_files, auds):
    """每段配音补静音到该段视频的精确时长，再拼成一整条 PCM 音轨。

    PCM 拼接无编码器 priming/padding，逐段时长精确对齐 → 全片零漂移。
    """
    d = os.path.join(WORK, 'au')
    os.makedirs(d, exist_ok=True)
    parts, total = [], 0.0
    for i, (seg, aud) in enumerate(zip(seg_files, auds)):
        vd = video_dur(seg)
        total += vd
        wav = os.path.join(d, f'a{i + 1:02d}.wav')
        subprocess.run([FFMPEG, '-y', '-v', 'error', '-i', aud,
                        '-af', 'apad', '-t', f'{vd:.3f}',
                        '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', wav],
                       check=True, capture_output=True)
        parts.append(wav)
    lst = os.path.join(d, 'au.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        for w in parts:
            f.write(f"file '{w}'\n")
    out = os.path.join(d, 'audio.wav')
    subprocess.run([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                    '-i', lst, '-c', 'copy', out], check=True, capture_output=True)
    print(f'   音轨 {total:.2f}s（逐段补静音到视频时长），'
          f'实际 {dur_of(out):.2f}s')
    return out


def assemble(seg_files, auds):
    """视频段 copy 拼接 → 与整条音轨一次封装。"""
    lst = os.path.join(WORK, 'concat.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        for s_ in seg_files:
            f.write(f"file '{s_}'\n")
    vid = os.path.join(WORK, 'video.mp4')
    subprocess.run([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                    '-i', lst, '-map', '0:v:0', '-c', 'copy', vid],
                   check=True, capture_output=True)
    wav = build_audio(seg_files, auds)
    subprocess.run([FFMPEG, '-y', '-v', 'error', '-i', vid, '-i', wav,
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
                    '-movflags', '+faststart', '-shortest', OUT],
                   check=True, capture_output=True)
    return OUT


def main():
    preview = '--preview' in sys.argv
    os.makedirs(WORK, exist_ok=True)
    print('[1/3] 准备配音')
    auds = [tts_get(i) for i in range(len(SEGS))]
    global DURS
    DURS = [dur_of(a) for a in auds]
    print('   各段时长:', [round(x, 1) for x in DURS], f'| 总配音 {sum(DURS):.0f}s')
    if '--remux' in sys.argv:
        # 只重拼（画面不动）：修复音轨漂移或改封装参数时用，几十秒完成
        print('[remux] 复用现有分段，仅重建音轨与封装')
        seg_files = [os.path.join(WORK, f'{TAG}seg{i + 1:02d}.mp4') for i in range(len(SEGS))]
        missing = [f for f in seg_files if not os.path.exists(f)]
        assert not missing, f'缺分段: {missing}'
        assemble(seg_files, auds)
        print(f'-> {os.path.abspath(OUT)}  ({os.path.getsize(os.path.abspath(OUT))/1e6:.1f} MB,'
              f' {video_dur(OUT):.1f}s)')
        return
    print('[2/3] 逐帧渲染动画（20fps）')
    seg_files = []
    for i, aud in enumerate(auds):
        if preview:
            out, dd = render_segment(i, aud, max_dur=2.5,
                                     out=os.path.join(WORK, f'{TAG}prev{i + 1:02d}.mp4'))
            print(f'  prev{i + 1:02d}  {dd:.1f}s')
            continue
        out = os.path.join(WORK, f'{TAG}seg{i + 1:02d}.mp4')
        if os.path.exists(out) and os.path.getsize(out) > 100000:
            print(f'  seg{i + 1:02d} 缓存复用')
        else:
            out, dd = render_segment(i, aud)
            print(f'  seg{i + 1:02d}  {dd:.1f}s')
        seg_files.append(out)
    if preview:
        print('-> 预览片段在 _video_work/prev*.mp4（每段前 2.5s）')
        return
    print('[3/3] 拼视频 + 拼音轨 + 封装')
    assemble(seg_files, auds)
    print(f'-> {os.path.abspath(OUT)}  ({os.path.getsize(os.path.abspath(OUT))/1e6:.1f} MB,'
          f' {video_dur(OUT):.1f}s)')


if __name__ == '__main__':
    main()
