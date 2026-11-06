# 制作流水线

## 0 环境

```bash
PY="C:/Users/Lenovo/AppData/Local/Programs/Python/Python313/python.exe"
```

- **双 Python**：bash 里的 `python` 没有三方库，凡是要 Pillow / edge-tts / nbclient 的，一律用上面的全路径
- 外部依赖：`ffmpeg`、`ffprobe` 在 PATH
- 幻灯片：`slidep` CLI
- TTS 需联网

---

## 1 PPT 侧（slidep DSL）

### 写一页

一页一个 `.slide`，是 JSX 片段（`<Slide>` 根节点）。参考 `templates/page.slide`。

### 写入

```bash
slidep upsert-dsl "x.pptx" --dsl-file "slides_v2/p09.slide" --page-index 8
```

`--page-index` 从 0 开始，文件名的 `p09` 对应 index 8，**容易差一**。

### 检查

```bash
slidep screenshot "x.pptx" --page-index 8 --out "tmp/p09.png"   # 出图看
slidep inspect "x.pptx" --out "tmp/outline.md"                   # 出大纲核页数
slidep lint "x.pptx" --dsl-file "slides_v2/p09.slide" --page-index 8   # 版式诊断
```

> `lint` 需要同时给 `--dsl-file` 才准；只给 pptx 会误报。

### 插入一页（slidep 没有插入命令）

降序改名，再整篇重灌：

```bash
# 要在第 10 页位置插新页，原 p10~p27 顺延
for i in 27 26 25 ... 10; do mv "p$i.slide" "p$((i+1)).slide"; done   # 必须降序
# 补上新的 p10.slide，然后
for i in $(seq 1 29); do
  slidep upsert-dsl "x.pptx" --dsl-file "$(printf 'slides_v2/p%02d.slide' $i)" --page-index $((i-1))
done
```

**降序是关键**，升序会互相覆盖。

---

## 2 视频侧（PIL 逐帧）

### 骨架

```
make_video.py
├─ 常量区    W/H/FPS/BG/配色/TAIL/MAX_ANIM/SERIES/EP/TAG
├─ 基础绘制  F() / mix() / ease() / bp() / txt() / panel() / circle() / arrow_h()
├─ chrome()  顶部标识 + 标题 + 底部时间轴（每帧都画）
├─ make_ch() 章封生成器
├─ draw_*()  每镜一个函数，签名 (d, t, dur)
├─ SEGS      镜头表：[{title, draw, ch, narr, plain?}]
├─ TTS       edge-tts 生成 mp3，按 narr md5 缓存
├─ render_segment()  单镜渲染（rawvideo 管道喂 ffmpeg）
└─ assemble()       逐段补静音拼 PCM → 拼视频 → 混流
```

### 节拍函数 bp()

```python
MAX_ANIM = 56.0

def bp(t, dur, start_f, span=0.06):
    eff = min(dur, MAX_ANIM)
    return ease((t - start_f * eff) / (span * eff))
```

**这是全片节奏的总开关。** 讲稿一变长，按比例铺开会让前 20 秒成为空页；`MAX_ANIM` 让动画最多铺 56 秒，之后停在完成态。

### 单镜重渲（改一镜不重渲全片）

```bash
# 1) 删掉该镜缓存
rm -f _video_work/v7seg09.mp4

# 2) 以模块方式单渲
$PY - <<'EOF'
import os, sys; sys.path.insert(0, os.getcwd())
import make_video as m
m.DURS = [m.dur_of(m.tts_get(i)) for i in range(len(m.SEGS))]
m.render_segment(8, m.tts_get(8), out=os.path.join(m.WORK, f'{m.TAG}seg09.mp4'))
EOF

# 3) 只重拼音轨与封装（约 1 分钟）
$PY make_video.py --remux
```

全量重渲 20 分钟左右，改一镜 1 分钟。**这是最该养成的习惯。**

### 缓存

| 缓存 | 位置 | 失效条件 |
|---|---|---|
| 配音 | `_video_work/tts_edge/{TAG}segNN_{md5}.mp3` | 讲稿文本变 / TAG 变 |
| 分段视频 | `_video_work/{TAG}segNN.mp4` | TAG 变（**改动画不失效，要手工删**） |

改讲稿 → 自动失效；只改动画或替换素材 → 必须手工删该镜 mp4，否则会用旧的。

---

## 3 音视频对齐（这一步最容易翻车）

**每个分段只编码视频轨，音轨最后一次性拼。**

原因：`concat -c copy` 会丢掉每段末尾 0.7 s 静音，音频逐段前移，90 秒处就差 1.2 秒（v5 实际发生过）。

正确做法：

1. 每段 `-an` 只出视频
2. 取视频精确时长：`nb_frames / FPS`（**不要用 duration 字段**，有累积误差）
3. 每段音频补静音到视频时长，拼成一条 PCM
4. 视频 concat + 音频混流

验证：`ffprobe` 看两个流的时长必须完全相等（如 879.350000 / 879.350000）。

---

## 4 静帧检查

```bash
$PY scripts/check_frames.py 3,7,12
```

按段号、在段内 4 个时间点出图到 `_video_work/chk/`。

**只看四件事**：重叠、裁切、超界、空页。这四样占版式问题的九成。

比看视频快 20 倍，本集所有间距问题都是这样发现的。

---

## 5 脱敏（发布前必做）

### 要脱的四类

| 类别 | 出现在哪 | 处理 |
|---|---|---|
| 工程名 | 文件名、fam 属性、阅读器截图、终端输出 | 换 `XX线Π接段` |
| 设计/施工单位 | 文件头 `编辑单位`、fam `生产厂家` | 换 `某省电力设计院` |
| 包名 | `dir` 输出、阅读器标题 | 换 `line04.gim` |
| 坐标 | `BLHA`、`POINTn` | 经纬度各减 0.5°，保留 4 位小数 |

### 坐标脱敏函数

```python
def mask_point(line, offset=0.5):
    key, sep, val = line.partition('=')
    if not sep: return line
    parts = val.split(',')
    if len(parts) >= 4:
        try:
            parts[1] = f'{float(parts[1]) - offset:.4f}'
            parts[2] = f'{float(parts[2]) - offset:.4f}'
        except ValueError: pass
    return f'{key}={",".join(parts)}'
```

只动第 2、3 列，点线拓扑与高差不变——所以"列序、量级、基准"的讲解依然成立，但落不到真实位置。

### 截图处理

阅读器截图含地图底图，会泄露位置。**裁掉右侧地图，只留左侧树面板**，再替换工程名与包名。

```
裁 x 0..352（面板右边界），通体无底图
覆盖 96..318 × 196..226 → 写"XX线Π接段 500kV 线路"
覆盖 186..282 × 36..62   → 写"line04.gim"
```

### 扫描残留

```bash
grep -rn "28\.24\|113\.14" --include=*.py --include=*.slide --include=*.md .
```

**别忘了旧备份脚本**（`make_video_v1.py` 曾经留着真实坐标）。

---

## 6 notebook 生成

**不要手抄一份代码**，从 `tutorial.py` 按 Step 注释切段生成：

```bash
$PY build_ipynb.py
```

坑：config 单元不能搬命令行解析——ipykernel 的 `sys.argv` 带 `-f kernel.json`，会把 `ROOT` 覆盖成 `-f`。只取常量本身。

验证：用 `nbclient` 实跑一遍，错误数必须为 0。

---

## 7 发布前清单

```
□ 工程名 / 单位名 / 包名脱敏（视频、PPT、脚本三处一致）
□ BLHA、POINTn 坐标已偏移，且标注"已脱敏"
□ 截图不含底图
□ PPT 与脚本数字逐项对齐（列一张表，别靠记忆）
□ 旧备份文件不含真实坐标（.py / .mp4 都要查）
□ 章节时间点与视频进度条对齐
□ 封面在移动端裁切后主体不被切
```
