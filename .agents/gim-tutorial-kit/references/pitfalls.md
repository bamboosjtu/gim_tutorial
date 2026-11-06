# 踩过的坑

> 每条都带现象 + 原因 + 解法。新一集开工前扫一遍，能省半天。

---

## A 渲染 / Pillow

### A1 · Consolas 把中文渲染成豆腐块

**现象**：`EP 01 · 线路篇` 里的"线路篇"显示成两个白方块。
**原因**：`consolab.ttf` 不含 CJK 字形，Pillow 不回退。
**解法**：含汉字的字符串一律用 `msyhbd.ttc` / `msyh.ttc`。判断条件只有一条——**字符串里有汉字吗**。

```python
def pick_font(s, size):
    has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in s)
    return F('reg' if has_cjk else 'mono', size)
```

### A2 · `ImageDraw.bitmap()` 贴 RGB 图报错

**现象**：`ValueError: bad transparency mask`
**原因**：`bitmap()` 只接受 1-bit 图或带 mask 的图，不接受 RGB。
**解法**：改用 `Image.paste()`，需要拿到当前帧的 Image 对象（见 A3）。

```python
img.paste(tile, (x, y))
```

### A3 · 绘图函数只拿到 ImageDraw，贴不了图

**现象**：想在 `draw_xxx(d, t, dur)` 里贴截图，但没有 Image 对象。
**原因**：`render_segment()` 里 `img` 是局部变量，`draw` 函数签名只有 `d`。
**解法**：模块级全局引用，渲染时赋值。

```python
CUR_IMG = [None]                      # 模块级
# render_segment 里：
img = Image.new('RGB', (W, H), BG)
CUR_IMG[0] = img
# draw 函数里：
CUR_IMG[0].paste(tile, (x, y))
```

用 list 而不是裸变量，省掉 `global` 声明。

### A4 · 逐帧 open 图片把渲染拖慢十倍

**现象**：贴了截图的那一段，渲染时间从 40 秒涨到 6 分钟。
**原因**：每帧都 `Image.open()` + `resize()`。
**解法**：按 `(路径, 尺寸)` 缓存。

```python
_TILE = {}
def tile(path, size):
    key = (path, size)
    if key not in _TILE:
        im = Image.open(path).convert('RGB').resize(size, Image.LANCZOS)
        _TILE[key] = im
    return _TILE[key]
```

---

## B 配音 / TTS

### B1 · `GIM → geem` 把 `GIMPKGT` 改坏了

**现象**：文件标识念成 "dinmpkgt"。
**原因**：全局替换把 `GIMPKGT` 里的 `GIM` 也换了。
**解法**：先保护长串，再替换短串。

```python
text = narr.replace('GIMPKGT', 'G I M P K G T').replace('GIM', 'geem')
```

**顺序不能反。**

### B2 · 改了替换逻辑，音频却没变

**现象**：修好 B1 后重新生成，还是念错。
**原因**：缓存键是 `md5(narr)`，`narr` 没变 → 命中旧文件。
**解法**：手工删该段 mp3 再生成。

```bash
rm -f _video_work/tts_edge/v7seg18_*.mp3
```

凡是**只改代码不改文本**的修复，都要手工清缓存。

### B3 · 下划线被念出来

**现象**：`Tower_Device` 念成 "Tower 下划线 Device"。
**解法**：讲稿改写 "Tower device"，或直接说"这个名字"。

### B4 · 英文复数念成另一个词

**现象**：`16 条 STRING` 念成 "16 条 stream"。
**解法**：改写"十六条挂点"，把缩写从口语里拿掉，画面里仍然显示原键名。

---

## C 音频 / 视频拼接

### C1 · 音画漂移，90 秒后差 1.2 秒

**现象**：口播和画面对不上，越往后越偏。
**原因**：分段 mp4 带了音轨，`concat -c copy` 丢掉了每段末尾 0.7 s 静音，音频逐段前移。
**解法**：分段只编码视频（`-an`），音频最后一次性拼。

流程见 `pipeline.md` 第 3 节。**验证方法**：`ffprobe` 看两个流时长必须完全相等。

### C2 · 用 `duration` 字段算时长，累积误差

**现象**：拼接后总时长对不上，差零点几秒。
**原因**：`ffprobe` 的 `duration` 是容器估算值，逐段累加会漂。
**解法**：用 `nb_frames / FPS`。

```python
if st.get('nb_frames'):
    return int(st['nb_frames']) / FPS
```

---

## D 幻灯片 / slidep

### D1 · 插入一页后中间页全被覆盖

**现象**：在第 10 页插新页，结果 p10~p27 只剩一半。
**原因**：`mv p10 p11` 之后再 `mv p11 p12`，把刚挪过去的又挪走了。
**解法**：**降序改名**。

```bash
for i in 27 26 ... 10; do mv "p$i.slide" "p$((i+1)).slide"; done
```

### D2 · 用区间替换改大段代码，把中间的函数删了

**现象**：改一页动画，结果 6 个绘图函数消失，程序 `NameError`。
**原因**：`s[:s.index(A)] + new + s[s.index(B):]`，A 和 B 之间的内容整段丢弃。B 写错位置就多删。
**解法**：
1. 改前 `cp make_video.py make_video.bak`
2. 锚点尽量贴近要换的内容，别跨函数
3. 改完立刻 `import` 一下验证

```bash
python -c "import ast;ast.parse(open('make_video.py',encoding='utf-8').read())"
python -c "import sys;sys.path.insert(0,'.');import make_video;print(len(make_video.SEGS))"
```

**没有 git 的项目，这是唯一的安全网。**（本集丢过 6 个函数，翻会话记录才捞回来。）

### D3 · heredoc 里的转义被吃掉

**现象**：`'''...\\'...'''` 写进文件后变成语法错误。
**原因**：bash heredoc + Python 三引号，反斜杠被多剥一层。
**解法**：中文引号用 `\u201c` `\u201d` 转义，或改用 `"` 包字符串。

### D4 · 预览面板锁住 pptx，覆盖失败

**现象**：`cp` 覆盖 `x.pptx` 报权限错误。
**原因**：预览面板持有独占句柄。
**解法**：另存新名；或关掉预览再覆盖。**不要反复重试 cp**，会一直失败。

### D5 · `upsert-dsl` 静默失败

**现象**：命令返回了，但截图还是旧的。
**解法**：每次 upsert 后 grep 一下返回，失败立刻看 `tail`。

```bash
slidep upsert-dsl "x.pptx" --dsl-file "p09.slide" --page-index 8 2>&1 | grep -o '"ok":[a-z]*'
```

`--page-index` 从 0 开始，文件名 `p09` → index 8，**最容易差一的地方**。

---

## E 数据 / 解析

### E1 · 把工程特征说成标准规定

**现象**：「每个耐张段要挂 11 个设备组」——听起来像标准常数。
**事实**：11 = 这个段的塔数(2) + 档数×相数(8) + 跨越数(1)；另一类耐张段是 64。
**解法**：数量一律写成"这个工程是这样"，标准侧只讲结构与职责。

### E2 · `cbm 指向 dev` 没限定层级

**现象**：说"cbm 指向 dev"，观众以为每一级都指。
**事实**：148 个设备组**一个 OBJECTMODELPOINTER 都没有**，343 条全在部件级。
**解法**：讲引用一定带层级限定——"设备组与部件的 cbm 指向 dev"。

### E3 · 把 cbm 与 fam 当一对一

**事实**：499 个 cbm 只有 350 个填了 `BASEFAMILY`（70%）；F3 级标准给了 `BASEFAMILY1~4` 四个槽位，部件级只有一个且允许为空。
**解法**：写"按需关联，不要求同名"。

### E4 · 变电包的 7z 签名不在 784

**现象**：读线路包正常的脚本，读某些变电包抛 `UnicodeDecodeError`。
**原因**：那批包的头是 768 + 8 字节，7z 在 776。
**解法**：识别并提示，不要硬解。

```python
if not raw_size.isdigit():
    alt = 776 if head800[776:782] == SEVEN_ZIP_SIG else None
    # 提示"另一种导出变体"，跳过长度自校验
```

### E5 · 遍历漏掉根文件的出边

**现象**：最小样本（2 个 cbm、1 条引用）跑出来"节点 1、边 0"。
**原因**：从 `project.cbm` 的 `SUBSYSTEM` 目标开始走，没算根自己的出边。
**解法**：根文件入队，算节点也算边。**口径要先定，再写代码**：

```
节点 = cbm 文件，含 project.cbm
边   = 父 cbm 里"值以 .cbm 结尾且键不以 .NUM 结尾"的键，一条键算一条边
多父 = 同一节点被两个及以上父引用；多出的边 = Σ(入度 − 1)
```

---

## F 其他

### F1 · 阅读器的原生对话框不接受合成输入

**现象**：`SendInput` 点击"打开 GIM"后进程直接退出，无崩溃事件、无日志。
**原因**：Tauri 的原生文件对话框在这个构建下不响应合成鼠标/键盘。
**解法**：放弃自动化，请人工打开后截图；或用已有截图做脱敏处理（见 `pipeline.md` 第 5 节）。

**顺带**：`WebView2` 固定运行时是 exe 自动加载的（`webview2-fixed-runtime` 目录，258 个文件），窗口能起就说明运行时没问题——**不要往运行时上找原因**。

### F2 · 截图底图泄露位置

**现象**：阅读器截图右侧是卫星底图，能反推出工程位置。
**解法**：裁掉右侧，只保留左侧层级树（`x 0..352`），再替换工程名与包名。裁剪后通体无底图。

### F3 · `MAX_ANIM` 之外还有个隐藏陷阱

**现象**：单镜讲稿从 40 秒涨到 60 秒，画面后半段是空页。
**原因**：所有 `bp()` 的 `start_f` 是**比例**，时长一长，绝对时间跟着拉长。
**解法**：`MAX_ANIM = 56`，`eff = min(dur, MAX_ANIM)`，动画最多铺 56 秒。

但**改了 `MAX_ANIM` 之后，章封那类短段（7–11 秒）不受影响**——`min()` 保证了这点。别以为它会把短段也压缩。

---

## 一句话总结

这套流程里真正会让人返工的，不是"不会画"，而是三类：

1. **缓存没失效**（改了代码但用了旧音频/旧视频）
2. **改代码误伤**（区间替换删函数、heredoc 吃转义）
3. **口径没说清**（数字、层级、边界）

前两类靠"备份 + 删缓存 + 立即验证"防，第三类靠写稿前先跑数防。
