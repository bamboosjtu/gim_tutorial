# -*- coding: utf-8 -*-
"""
tutorial.py —— 线路 GIM 文件拆解（新手向，与《线路GIM文件拆解.pptx》29 页五章对应）

使用前提
    1. 解包目录 ROOT：里面能看到 Cbm/Dev/Phm/Mod 四个子目录（Step 2 起需要）；
    2. 原包 GIM：.gim 文件路径，只有 Step 1 读容器头需要；
    3. 也可以命令行指定：python tutorial.py <解包目录> [原包] [--step=N]
       只看容器头时 ROOT 可以留空：python tutorial.py "" line04.gim --step=1

十步目录（对应 PPT 页码）
    1 容器头   : 11 个定长字段 / NUL 结尾 / 存储域大小        （P4）
    2 四目录   : Cbm/Dev/Phm/Mod + 两份语义普查               （P5）
    3 格式速览 : .cbm/.fam/.dev/.phm 真实样例                 （P16~P17）
    4 几何格式 : .mod 五族判型 + .stl 二进制 + POINTn 坐标    （P18）
    5 F1~F4下钻: 每步两道证明（NUM 计数 + 读回 ENTITYNAME）    （P11~P12）
    6 引用图   : BFS 遍历 + 节点/边/入度分布 + 叶子普查        （P19）
    7 主链跳转 : SUBSYSTEM 的值就是"下一个文件名"              （P13）
    8 三种指针 : 把四个目录缝成一个整体                        （P22）
    9 属性 FAM : 三段式 + 按需关联（不是一对一）               （P16）
    10 陷阱清单: 六份样本里真实踩过的坑                        （P29）

口径约定（与 PPT / 视频完全一致）
    · 节点 = cbm 文件，含根文件 project.cbm
    · 边   = 父 cbm 里"值以 .cbm 结尾且键不以 .NUM 结尾"的键，一条键算一条边
    · 多父 = 同一节点被两个及以上父节点引用；多出的边 = Σ(入度 − 1)
"""
import os
import re
import sys
import glob
import struct
import collections

# ================================================================ CONFIG
ROOT = r''   # 解包后的 GIM 目录（含 Cbm/Dev/Phm/Mod）；只看 Step 1 时可留空
GIM = r''    # .gim 原包路径（Step 1 用）

# 命令行可临时覆盖：python tutorial.py <解包目录> [原包] [--step=N]
_args = [a for a in sys.argv[1:] if not a.startswith('--')]
if len(_args) >= 1:
    ROOT = _args[0]
if len(_args) >= 2:
    GIM = _args[1]
STEP = None
for _a in sys.argv[1:]:
    if _a.startswith('--step'):
        STEP = int(_a.split('=', 1)[1]) if '=' in _a else None

if not ROOT and STEP != 1:
    print('请先填写 CONFIG 区：')
    print('    ROOT = r"D:\\data\\line04"   # 解包目录（含 Cbm/Dev/Phm/Mod）')
    print('    GIM  = r"D:\\data\\line04.gim"  # 原包，Step 1 用')
    print('或不填直接运行: python tutorial.py <解包目录> [原包]')
    print('只看容器头可以不要解包目录: python tutorial.py "" line04.gim --step=1')
    sys.exit(0)

# ================================================================ 小工具
def subdir(root, *names):
    """按小写名称匹配子目录——坑②：厂商会导出 Cbm 也会导出 CBM，大小写不定。"""
    if not root:
        return None
    entries = {e.casefold(): e for e in os.listdir(root)}
    for n in names:
        hit = entries.get(n.casefold())
        if hit and os.path.isdir(os.path.join(root, hit)):
            return os.path.join(root, hit)
    return None


def count_files(directory):
    """按扩展名统计目录内文件（大小写不敏感），返回 {'.cbm': n, ...}。"""
    c = collections.Counter()
    for e in os.listdir(directory):
        stem, ext = os.path.splitext(e)
        if ext:
            c[ext.lower()] += 1
    return c


def kv(path, maxsplit=1):
    """cbm / dev / phm / mod 都是 key=value 行文本。

    maxsplit=1：值里可以再出现 '='（如 fam 的"中文=关键字=值"用 fam_rows 读）。
    不做 try/except —— 文件缺失、编码错误要原样抛出来，教学代码不该假装成功。
    """
    d = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('//') or '=' not in line:
                continue
            k, v = line.split('=', maxsplit)
            d[k.strip()] = v.strip()
    return d


def fam_rows(path):
    """fam 是三段式：属性名 = 属性关键字 = 值。

    关键字可以为空（如"部件生产厂家==国网金具库"），所以必须 split('=', 2)，
    再用 maxsplit 保证值里含 '=' 也不会把行切碎。
    """
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith('//'):
                continue
            parts = line.split('=', 2)
            if len(parts) < 3:                      # 只有两段的行不算合法属性行
                rows.append((parts[0], None, parts[1] if len(parts) == 2 else ''))
            else:
                rows.append(tuple(p.strip() for p in parts))
    return rows


def mask_point(line, offset=0.5):
    """POINTn=序号,纬度,经度,高程,类型 —— 经纬度各减 offset 脱敏，其余原样。

    只动第 2、3 列（保留 4 位小数，约 11 m 精度）：形状、高差、点线拓扑不变，
    所以这一页讲的"列序、量级、基准"依然成立，但落不到任何真实位置。
    """
    key, sep, val = line.partition('=')
    if not sep:
        return line
    parts = val.split(',')
    if len(parts) >= 4:
        try:
            parts[1] = f'{float(parts[1]) - offset:.4f}'
            parts[2] = f'{float(parts[2]) - offset:.4f}'
        except ValueError:
            pass
    return f'{key}={",".join(parts)}'


def banner(no, title, page):
    print('\n' + '=' * 72)
    print(f'Step {no:<2d} {title}　（PPT {page}）')
    print('-' * 72)


def need_cbm():
    """Step 2 起才要求解包目录；把校验放在函数里，Step 1 才能单独跑。

    只要读层级/引用图（Step 5~7）时，最小样本可以只有一个 Cbm 目录，
    所以 Dev 在这里不强制存在。
    """
    cbm = subdir(ROOT, 'Cbm', 'CBM')
    if not cbm:
        raise SystemExit(f'不是解包后的 GIM 目录: {ROOT!r}（缺 Cbm）')
    return cbm, subdir(ROOT, 'Dev', 'DEV'), subdir(ROOT, 'Phm', 'PHM'), subdir(ROOT, 'Mod', 'MOD')


def need_dirs():
    """涉及 Dev 的步骤（格式样例、指针、FAM）才要求 Dev 目录。"""
    cbm, dev, phm, mod = need_cbm()
    if not dev:
        raise SystemExit(f'{ROOT!r} 下没有 Dev 目录，本步需要它')
    return cbm, dev, phm, mod


# ---------------------------------------------------------------- Step 1
# Q/GDW 11809—2023 表 A.1：文件头 11 个定长字段，顺序固定
FIELD_SIZES = (
    (16, '文件标识'), (256, '文件名称'), (64, '编辑者'), (256, '编辑单位'),
    (128, '软件名称'), (16, '创建时间'), (8, '主版本号'), (8, '次版本号'),
    (8, '修订号'), (8, '构建号'), (16, '存储域大小'),
)
HEADER_SIZE = sum(s for s, _ in FIELD_SIZES)          # = 784
SEVEN_ZIP_SIG = b'7z\xbc\xaf\x27\x1c'


def step1_container():
    banner(1, '容器头：784 字节 = 表 A.1 十一个定长字段之和', 'P4')
    if not (GIM and os.path.exists(GIM)):
        print('   （GIM 原包未指定或不存在，跳过）')
        print('   用法: python tutorial.py "" line04.gim --step=1')
        return

    file_size = os.path.getsize(GIM)
    with open(GIM, 'rb') as f:
        head = f.read(HEADER_SIZE)
        if len(head) != HEADER_SIZE:
            raise ValueError(f'{GIM} 不足 {HEADER_SIZE} 字节（只有 {len(head)}），不是 GIM 容器')
        f.seek(HEADER_SIZE)
        sig = f.read(len(SEVEN_ZIP_SIG))

    # 按占位长度一段一段切：位置由字段序号决定，不靠"非空段"凑
    off = 0
    fields = []
    for size, name in FIELD_SIZES:
        raw = head[off:off + size]
        fields.append((name, size, off, raw.split(b'\x00', 1)[0]))   # 值以 NUL 结尾
        off += size

    print(f'   文件 {os.path.basename(GIM)}  {file_size:,} 字节')
    print(f'   {"字段":<12s}{"偏移":>6s}{"长度":>6s}   值')
    for name, size, o, raw in fields:
        txt = raw.decode('utf-8', 'replace').strip()
        print(f'   {name:<12s}{o:>6d}{size:>6d}   {txt if txt else "（空）"}')

    raw_size = fields[-1][3]
    if not raw_size.decode('ascii', 'ignore').strip().isdigit():
        # 见过另一种导出变体：768 之后只放 8 字节二进制，7z 从 776 开始
        head800 = open(GIM, 'rb').read(800)
        alt_sig_at = 776 if head800[776:782] == SEVEN_ZIP_SIG else None
        print(f'\n   存储域大小字段不是十进制文本（原始字节 {raw_size!r}）')
        if alt_sig_at:
            print(f'   压缩域签名在 {alt_sig_at} 处，说明这个包的头是 768 + 8 字节，属于另一种导出变体')
        else:
            print('   也没有在预期位置找到 7z 签名，容器可能不是标准导出')
        print(f'   本课以 784 的线路包为准；这个包可以继续用，但长度自校验不适用')
        return

    payload_size = int(raw_size.decode('ascii').strip())
    print(f'\n   存储域大小 = {payload_size:,} 字节')
    total_ok = HEADER_SIZE + payload_size == file_size
    print(f'   784 + {payload_size:,} = {HEADER_SIZE + payload_size:,}'
          f'　实际 {file_size:,}　{"✓ 一致" if total_ok else "✗ 不一致，文件被截断或改写"}')
    print(f'   784 处的签名: {sig!r}　{"✓ 7z" if sig == SEVEN_ZIP_SIG else "✗ 不是 7z"}')
    print('   注意：字段值以 NUL 结尾、空字段只留 NUL —— 按下标读，不要按"非空段序号"读')


# ---------------------------------------------------------------- Step 2
def step2_dirs():
    banner(2, '四个目录 + 语义普查：数一遍就知道这包里有什么', 'P5')
    cbm, dev, phm, mod = need_dirs()
    print(f'   解包目录: {ROOT}')
    # 标准侧：目录与文件职责固定（Q/GDW 11809—2023 §6）；实例侧：数量由工程规模定
    roles = {'Cbm': '组装模型 *.cbm + 本层属性 *.fam  → 层级与装配',
             'Dev': '物理模型 *.dev + 参数表 *.fam   → 这是什么',
             'Phm': '几何模型组 *.phm                  → 由哪些零件组成',
             'Mod': '几何 *.mod / *.stl               → 长什么样'}
    for d, label in ((cbm, 'Cbm'), (dev, 'Dev'), (phm, 'Phm'), (mod, 'Mod')):
        print(f'   {label}: {roles[label]}')
        if not d:
            print('        （目录不存在，跳过）')
            continue
        n = count_files(d)
        print('        本样本实测: %s（合计 %d 个文件）' % (' · '.join(
            f'{k[1:]} {v:4d}' for k, v in sorted(n.items()) if v), sum(n.values())))
    print('   ※ 标准只规定四个目录与各类文件的职责，不规定数量；以上数字随工程规模变化')

    tree = collections.Counter(kv(f).get('ENTITYNAME', '?')
                              for f in glob.glob(os.path.join(cbm, '*.cbm')))
    print('\n   —— Cbm 层 ENTITYNAME（线路不是 F1~F4 一套代号到底）——')
    for name, n in tree.most_common():
        print(f'      {name:14s} {n}')

    dt = collections.Counter(kv(f).get('DEVICETYPE', '?')
                             for f in glob.glob(os.path.join(dev, '*.dev')))
    print('   —— Dev 层 DEVICETYPE（线路独立字典，别拿变电的套）——')
    for name, n in dt.most_common():
        print(f'      {name:14s} {n}')


# ---------------------------------------------------------------- Step 3
def step3_formats():
    banner(3, '格式速览：.cbm/.fam/.dev/.phm 都是 key=value 行文本', 'P16~P17')
    cbm, dev, phm, mod = need_dirs()

    def show(title, path, n=8):
        if not path:
            print(f'   —— {title} ——（无样本，跳过）\n')
            return
        print(f'   —— {title} ——')
        with open(path, encoding='utf-8') as fp:
            shown = 0
            for line in fp:
                if shown >= n:
                    break
                if line.strip():
                    print('      ' + line.rstrip())
                    shown += 1
        print()

    def first(pattern):
        hits = sorted(glob.glob(pattern))
        return hits[0] if hits else None

    show('Dev 层 .dev（设备定义：类型 + 参数表 + 零件表 + 位姿）',
         first(os.path.join(dev, '*.dev')), 7)
    show('Phm 层 .phm（零件拆分：每个零件 = 一个 .mod + 位姿 + 颜色）',
         first(os.path.join(phm, '*.phm')) if phm else None, 8)
    show('Cbm 层 .fam（属性挂层级节点，三段式：中文=英文=值）',
         first(os.path.join(cbm, '*.fam')), 6)
    show('Dev 层 .fam（设备参数表）',
         first(os.path.join(dev, '*.fam')), 6)


# ---------------------------------------------------------------- Step 4
def mod_family(first_line):
    """同一个 .mod 扩展名下五种写法，判型只看首行。"""
    s = first_line.strip()
    low = s.lower()
    if low.startswith('code='):
        code = s.split('=', 1)[1].strip()
        return 'CODE=1019 截面构件族' if code == '1019' else 'CODE 点+线族'
    if low.startswith('bolt'):
        return 'Bolt 螺栓阵列族'
    if low.startswith('type='):
        return 'TYPE 型材族'
    if low.startswith('hnum'):
        return 'HNum 杆塔族'
    return '其他'


def step4_mod():
    banner(4, '几何：.mod 五族判型 + .stl 二进制校验 + POINTn 坐标', 'P18')
    cbm, dev, phm, mod = need_dirs()
    if not mod:
        print('   （无 Mod 目录，跳过）')
        return
    stat = collections.Counter()
    sample = None
    for f in sorted(glob.glob(os.path.join(mod, '*.mod'))):
        with open(f, encoding='utf-8') as fp:
            first = next((ln.strip() for ln in fp if ln.strip()), '')
        fam = mod_family(first)
        stat[fam] += 1
        if fam == 'CODE 点+线族' and sample is None:
            sample = f
    for k, v in stat.most_common():
        print(f'   {k:20s} {v}')
    if sample:
        print(f'\n   CODE 族样例 {os.path.basename(sample)}（经纬度已整体偏移脱敏）：')
        with open(sample, encoding='utf-8') as fp:
            for line in fp:
                line = line.rstrip('\r\n')
                if re.match(r'POINT\d+=', line):
                    print('      ' + mask_point(line))
                elif line.startswith(('CODE', 'POINTNUM', 'LINENUM')):
                    print('      ' + line)
        print('   脱敏规则：经纬度各减 0.5°，点线拓扑与高差不变；本脚本与配套 PPT 用同一套偏移值。')
        print('   第 2~4 列是"纬度、经度、高程"，量级 2x.xx°N / 11x.xx°E / 4x~6x m；')
        print('   文件本身不声明基准：Q/GDW 11798.2—2023 §4.3.3 规定成果应采用')
        print('   CGCS2000 地理坐标 + 1985 国家高程基准——不要按 WGS84 解读。')
    stls = sorted(glob.glob(os.path.join(mod, '*.stl')))
    if stls:
        raw = open(stls[0], 'rb').read()
        n_tri = struct.unpack('<I', raw[80:84])[0]
        ok = 84 + 50 * n_tri == len(raw)
        print(f'\n   .stl（Binary / ASCII 两种表达；本样本实测为 Binary）：'
              f'{len(raw):,} B = 80 头 + uint32 计数 + 50B×{n_tri} 三角形'
              f'　{"✓ 尺寸相符" if ok else "✗ 尺寸对不上"}')
        print('   判型规则：先确认 STL 是 Binary 还是 ASCII；.mod 才用"首行键"判族')


# ---------------------------------------------------------------- Step 5
def step5_drill():
    banner(5, 'F1~F4 下钻：每步两道证明（NUM 计数 + 读回身份）', 'P11~P12')
    cbm, dev, phm, mod = need_cbm()

    def drill(node, key, num, want):
        kids = [v for k, v in node.items()
                if k.startswith(key) and v.endswith('.cbm')]
        assert int(node[num]) == len(kids), f'{num}: {node[num]} != {len(kids)}'
        for v in kids:
            d = kv(os.path.join(cbm, v))
            # 大小写归一：标准写 F2SYSTEM，实例可能是 F2System
            assert d.get('ENTITYNAME', '').upper() == want, \
                f'{v}: {d.get("ENTITYNAME")} != {want}'
        return kids

    f1 = kv(os.path.join(cbm, kv(os.path.join(cbm, 'project.cbm'))['SUBSYSTEM']))
    print(f'   project.cbm --SUBSYSTEM--> {f1.get("ENTITYNAME")} ✓')
    f2s = drill(f1, 'SECTION', 'SECTIONS.NUM', 'F2SYSTEM')
    print(f'   F1 --SECTIONn--> F2System ×{len(f2s)} ✓')
    f3s = []
    for v in f2s:
        f3s += drill(kv(os.path.join(cbm, v)),
                     'STRAINSECTION', 'STRAINSECTIONS.NUM', 'F3SYSTEM')
    print(f'   F2 --STRAINSECTIONn--> F3System 耐张段 ×{len(f3s)} ✓')
    refs = []
    for v in f3s:
        refs += drill(kv(os.path.join(cbm, v)), 'GROUP', 'GROUPS.NUM', 'F4SYSTEM')
    print(f'   F3 --GROUPn--> F4System：{len(refs)} 条引用，唯一 {len(set(refs))} 个')
    print('   （引用数 > 唯一数：边界塔被两个耐张段共用，统计要按 UUID 去重）')

    # 每个耐张段挂多少组、都是什么组 —— 组数不是标准常数，是塔/档/跨越的数量
    print('   每个耐张段的组构成：')
    for v in f3s:
        n3 = kv(os.path.join(cbm, v))
        kids = [x for k, x in n3.items() if k.startswith('GROUP') and not k.endswith('.NUM')]
        c = collections.Counter(kv(os.path.join(cbm, x)).get('GROUPTYPE', '?') for x in kids)
        print(f'      {v[:8]}  {len(kids):3d} 组 = '
              + ' · '.join(f'{k} {n}' for k, n in sorted(c.items())))


# ---------------------------------------------------------------- Step 6
def step6_walk():
    banner(6, '引用图 BFS：一个判据走完全图，节点/边/入度一起出来', 'P19')
    cbm, dev, phm, mod = need_cbm()

    seen = {}                                   # 节点 -> ENTITYNAME
    parents = collections.defaultdict(list)     # 子 -> [父, ...]（含重复边）
    levels = collections.Counter()
    leaves = collections.Counter()
    edges = 0

    q = collections.deque([('project.cbm', 0)])  # 广度优先；根文件也是节点、也贡献出边
    while q:
        uid, depth = q.popleft()
        if uid in seen:                          # 已访问：不再展开，但入边在上面已记过
            continue
        node = kv(os.path.join(cbm, uid))
        name = node.get('ENTITYNAME') or ('project.cbm' if uid == 'project.cbm' else '?')
        seen[uid] = name
        levels[f'{depth}|{name}'] += 1
        kids = [v.strip() for k, v in node.items()
                if v.endswith('.cbm') and not k.endswith('.NUM')]
        edges += len(kids)                       # 一条键 = 一条引用边
        if not kids and uid != 'project.cbm':
            leaves[name] += 1
        for v in kids:
            parents[v].append(uid)
            q.append((v, depth + 1))

    for k in sorted(levels):
        d, name = k.split('|', 1)
        print(f'   L{d} {name:14s} ×{levels[k]}')
    print('   —— 叶子普查（没有子指针的节点）——')
    for n, c in leaves.most_common():
        print(f'      {n:14s} {c}')

    multi = {k: v for k, v in parents.items() if len(v) > 1}
    indeg = collections.Counter(len(v) for v in multi.values())
    extra = sum(len(v) - 1 for v in multi.values())
    print(f'\n   唯一节点 {len(seen)}（含 project.cbm）　引用边 {edges} 条')
    print(f'   有入边的节点 {len(parents)}　多父节点 {len(multi)}　多出的边 {extra} 条')
    if indeg:
        print('   多父节点的入度分布：' + ' · '.join(f'入度{k}: {v} 个'
                                          for k, v in sorted(indeg.items())))
    print('   边比节点多，是"同一文件被多个父引用"，不是 bug；')
    print('   统计实体数量按 UUID 去重，统计引用关系统计边。')


# ---------------------------------------------------------------- Step 7
def step7_chain():
    banner(7, '主链跳转：SUBSYSTEM 的值就是"下一个文件名"', 'P13')
    cbm, dev, phm, mod = need_cbm()
    print('   （以下为"每层取第一条出边"的主链示例，不是完整遍历——')
    print('    完整遍历见 Step 6；每个带 .NUM 的键都说明本层还有更多分支）')
    node = kv(os.path.join(cbm, 'project.cbm'))
    nxt = node['SUBSYSTEM']
    depth = 0
    while nxt and depth < 12:
        node = kv(os.path.join(cbm, nxt))
        print(f'   → {node.get("ENTITYNAME", "?"):14s} <- {nxt[:8]}….cbm')
        nxt = next((v for k, v in node.items()
                    if v.endswith('.cbm') and not k.endswith('.NUM')), '')
        depth += 1
    print('   （值不是 ID 也不是 URL，就是同目录里的下一个文件名——每跳一步读回 ENTITYNAME 验证）')


# ---------------------------------------------------------------- Step 8
def step8_pointers():
    banner(8, '三种指针 + Dev 装配，把四个目录缝成一个整体', 'P22')
    cbm, dev, phm, mod = need_dirs()
    n_dev2dev = sum(1 for f in glob.glob(os.path.join(dev, '*.dev'))
                    for k, v in kv(f).items()
                    if k.startswith('SUBDEVICE') and v.endswith('.dev'))
    n_solid_dev = sum(1 for f in glob.glob(os.path.join(dev, '*.dev'))
                      for k, v in kv(f).items()
                      if k.startswith('SOLIDMODEL') and v.lower().endswith('.dev'))
    n_cbm_sub = sum(1 for f in glob.glob(os.path.join(cbm, '*.cbm'))
                    for k, v in kv(f).items()
                    if k.startswith('SUBDEVICE') and k != 'SUBDEVICES.NUM'
                    and v.endswith('.cbm'))
    omp = sum(1 for f in glob.glob(os.path.join(cbm, '*.cbm'))
              if kv(f).get('OBJECTMODELPOINTER', '').endswith('.dev'))
    print(f'   Dev SUBDEVICE→.dev   : {n_dev2dev}（变电的装配键名，线路通常为 0）')
    print(f'   Dev SOLIDMODELn→.dev : {n_solid_dev}（线路装配键名：组合设备 → 子设备）')
    print(f'   Cbm SUBDEVICE→.cbm   : {n_cbm_sub}')
    print(f'   Cbm →Dev 模型指针    : {omp}')
    for f in sorted(glob.glob(os.path.join(cbm, '*.cbm'))):
        d = kv(f)
        ompv = d.get('OBJECTMODELPOINTER', '')
        if ompv.endswith('.dev'):
            dv = kv(os.path.join(dev, ompv))
            print(f'\n   示例链: {os.path.basename(f)[:8]}…cbm  ENTITYNAME={d.get("ENTITYNAME")}')
            print(f'      → OBJECTMODELPOINTER = {ompv[:8]}…dev  DEVICETYPE={dv.get("DEVICETYPE")}')
            base = dv.get('BASEFAMILY', '')
            if base.endswith('.fam'):
                fam = kv(os.path.join(dev, base))
                print(f'      → BASEFAMILY = {base[:8]}…fam  属性键如: {list(fam)[:4]}')
            break
    print('\n   注：部件 cbm 里没有 DEVICETYPE——类型要跟 OBJECTMODELPOINTER 到 dev 去读')


# ---------------------------------------------------------------- Step 9
def step9_fam():
    banner(9, '属性 FAM：按需关联，不是一对一', 'P16')
    cbm, dev, phm, mod = need_dirs()

    # Cbm 层：多少个 cbm 真的挂了 fam
    cbms = glob.glob(os.path.join(cbm, '*.cbm'))
    with_fam = sum(1 for f in cbms if kv(f).get('BASEFAMILY', '').strip())
    fam_files = glob.glob(os.path.join(cbm, '*.fam'))
    print(f'   Cbm 层 cbm {len(cbms)} · fam {len(fam_files)}')
    print(f'   填了 BASEFAMILY 的 cbm：{with_fam}（{with_fam / max(len(cbms), 1):.0%}）；'
          f'值为空：{len(cbms) - with_fam}')

    # Dev 层：指针可达 / 悬空 / 未写
    n_dev = len(glob.glob(os.path.join(dev, '*.dev')))
    n_fam = len(glob.glob(os.path.join(dev, '*.fam')))
    ok = bad = no_base = 0
    for f in glob.glob(os.path.join(dev, '*.dev')):
        base = kv(f).get('BASEFAMILY', '').strip()
        if not base:
            no_base += 1
        elif os.path.exists(os.path.join(dev, base)) or os.path.exists(os.path.join(cbm, base)):
            ok += 1
        else:
            bad += 1                             # 有指针但目标不存在（悬空）
    print(f'   Dev 层 dev {n_dev} · fam {n_fam}')
    print(f'   BASEFAMILY：有指针 {ok + bad}（可达 {ok} · 悬空 {bad}）· 未写指针 {no_base}')

    sample = sorted(glob.glob(os.path.join(cbm, '*.fam')))
    if sample:
        print(f'\n   样例 {os.path.basename(sample[0])}：')
        for name, key, val in fam_rows(sample[0])[:6]:
            print(f'      {name:<14s} 关键字={key!r:<24s} 值={val}')
    print('\n   三段式只能 split("=", 2)：关键字可以为空，值里也可能有 "="。')
    print('   标准里 F3 级给了 BASEFAMILY1~4 四个槽位，部件级一个、且允许为空——')
    print('   所以"一个 cbm 对应一个 fam"是巧合，不是规则；配对一律看指针。')


# ---------------------------------------------------------------- Step 10
def step10_pitfalls():
    banner(10, '陷阱清单：六份样本里真实踩过的坑', 'P29')
    print('''   ① 头按字段切   11 个定长字段、顺序固定、值以 NUL 结尾；
      空字段只留一个 NUL，按"非空段序号"读会错位。
   ② 目录大小写   Cbm/CBM、Dev/DEV、Mod/MOD 并存，查目录永远两种都试。
   ③ 判型看首行   .mod 五种写法（CODE / CODE=1019 / Bolt / TYPE / HNum），
      只认首行键；STL 有 Binary/ASCII 两种表达，先确认再解析。
   ④ 装配键不同   变电 Dev 用 SUBDEVICE→.dev；线路 Dev 用
      SOLIDMODELn→.dev（组合）或 →.phm（叶子）——照搬变电键名一条也找不到。
   ⑤ 计数先定口径 节点含 project.cbm、边按"键"算、多父按入度算；
      口径不定，499/779 这种数字每次跑出来都不一样。

   跑完十步，你已经能独立读懂一份线路 GIM：
   容器头 → 四目录 → 格式 → 几何 → 下钻 → 引用图 → 主链 → 指针 → FAM → 陷阱。''')


STEPS = [step1_container, step2_dirs, step3_formats, step4_mod, step5_drill,
         step6_walk, step7_chain, step8_pointers, step9_fam, step10_pitfalls]


def main():
    print('线路 GIM 文件拆解 · 解包目录:', ROOT or '（未指定）')
    if GIM and os.path.exists(GIM):
        print('                      原包    :', GIM)
    if STEP is not None:
        STEPS[STEP - 1]()
    else:
        for fn in STEPS:
            fn()
    print('\n' + '=' * 72)
    print('完。推荐学习路径：本脚本 → 教程案例/gim_walk_line.py → gim_locate_line.py → gim_check_line.py')


if __name__ == '__main__':
    main()
