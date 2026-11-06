---
name: gim-tutorial-kit
description: 制作国网 GIM / 输变电三维设计系列教学视频与配套教材时使用。覆盖选题定位、五章结构、slidep 幻灯片 DSL、PIL 逐帧动画、edge-tts 配音、封面生成、B 站发布、样本数据核对与脱敏。当用户要做这类教程视频、改讲义 PPT、写分镜与口播稿、做封面、核对样本数字或查坐标脱敏时触发。
version: 1.0
base: EP01《线路 GIM 文件拆解》（14:39 / 20 镜 / 29 页 PPT）
---

# GIM 教学视频与教材制作工具包

## 这个 skill 解决什么

把一份国网三维设计标准（GIM 系列）拆成**能被新手看懂的视频 + 讲义 + 可运行脚本**三件套。

它约束的不是"怎么做视频"，而是三件容易做错的事：

1. **数字怎么说才站得住**——每个数都要能追到口径和样本
2. **标准怎么讲才不误导**——条文号、表号、适用层级，一个都不能少
3. **工程特征怎么讲才不外推**——"这个包是这样"≠"所有实现都这样"

## 什么时候用

| 触发 | 典型说法 |
|---|---|
| 做新一集 | "做变电篇""EP02 开工""再拆一个样本" |
| 改现有教材 | "这页讲错了""PPT 和视频口径不一致""改一下第 5 段" |
| 写口播/分镜 | "出个分镜稿""这段话念着别扭""配个音" |
| 做封面/发布 | "做个封面""写个 B 站简介" |
| 核对数据 | "这些数字对不对""坐标脱敏了吗" |

## 资产地图

```
tutorial/
├─ .agents/gim-tutorial-kit/          ← 本 skill
│  ├─ SKILL.md                        主入口（你正在读）
│  ├─ references/
│  │  ├─ visual-system.md             配色 / 字号 / 七种组件 / 版式网格
│  │  ├─ narrative.md                 五章结构 / 句法 / 词汇 / TTS 读音约定
│  │  ├─ pipeline.md                  五步流程 / 命令 / 缓存 / 拼接
│  │  ├─ pitfalls.md                  18 个真实踩过的坑
│  │  └─ ep01-structure.md            EP01 的 29 页编排与六轮修订史（参照用）
│  ├─ scripts/                        ← 四个工具脚本，全部带复用说明头
│  │  ├─ check_frames.py              抽静帧检查版式（支持 --real 用真实时长）
│  │  ├─ make_cover.py                生成 16:10 封面（改 7 处文案即可）
│  │  ├─ make_shotlist.py             从 SEGS + 真实配音时长出分镜稿
│  │  └─ build_ipynb.py               从 tutorial.py 切段生成 notebook
│  └─ templates/
│     ├─ make_video_reference.py      EP01 完整渲染实现（20 镜，105 KB）
│     └─ page.slide                   一页 slidep DSL 样例
└─ 01-GIM/                             ← EP01 产物（只留成品 + 发布材料）
   ├─ 01-线路工程拆解/
   │  ├─ tutorial.py                  十步解析脚本（成品）
   │  ├─ tutorial.ipynb               交互版 24 格（由 tutorial.py 切段生成）
   │  ├─ assets/tree_panel.png        阅读器树截图（已脱敏，重渲视频时要用）
   │  └─ 线路GIM文件拆解/
   │     ├─ 线路GIM文件拆解.pptx        29 页讲义（成品）
   │     └─ slides_v2/                29 页 DSL 源（要改 PPT 才动这里）
   ├─ 线路GIM拆解讲解视频.mp4           成片 14:39 / 29 MB
   ├─ 封面-线路GIM拆解.png              封面 1920×1200
   ├─ B站发布方案.md                    标题 / 简介 / 标签 / 系列规划
   └─ 视频分镜与口播稿.md               逐镜画面要点 + 口播全文 + 时间码
```

**脚本与设计文档一律以本 skill 为准**，EP01 目录里不留副本。要重出视频时，
把 `templates/make_video_reference.py` 复制成工作目录的 `make_video.py`，
再把 `scripts/` 下的工具脚本放同目录即可。

## 五步流程

### 第 1 步 · 定主题（不写代码）

一句话说清"这一集拆什么"，**必须能直接当封面标题**。写不出来就是选题没想清。

判定标准：这句话里要有一个具体的落点（字节数、层级数、一个文件名），不能是"介绍 XX 标准"。

> ✅「一条 .gim 里到底装了什么？从 784 字节拆到一根绝缘子串」
> ❌「输变电三维设计 GIM 标准介绍」

### 第 2 步 · 先跑数，再写稿

**顺序不能反。** 先写脚本把样本跑一遍，拿到真实的节点数、边数、文件数、分布，再动笔。

理由：写稿时凭印象编一个数字，后面每一页都要为它圆谎；跑出来再写，数字自己会组织段落。

```bash
python tutorial.py "<解包目录>"              # 十步全跑
python tutorial.py "<解包目录>" --step=6     # 只跑引用图
python tutorial.py "" "<x>.gim" --step=1     # 只读容器头（不需要解包）
```

### 第 3 步 · 分五章、配镜头

按 `references/narrative.md` 的五章模板填，每章 3–5 镜。节奏公式：

```
序 30s → 章封 ×5（各 7–11s）→ 正片 ≤90s/镜 → 实操 1 镜（可 2 倍长）→ 收尾 70s
```

章封不是"休息"，是"报进度"：章号 + 章名 + 一行提要 + 一句引导语 + 五个进度点。

### 第 4 步 · 先出静帧，再配音

**先检查画面，再花钱配音。** 配音一改，整镜时长变，画面节奏全要重算。

```bash
python scripts/check_frames.py 3,7,12    # 按段号出静帧到 _video_work/chk/
```

静帧只看四件事：**重叠、裁切、超界、空页**。这四样占版式问题的九成。

### 第 5 步 · 渲染、拼接、发布

```bash
python make_video.py                 # 全量渲染 + 拼接
python make_video.py --remux         # 只重拼音轨与封装（改了一两镜时用）
```

发布前必做 `references/pipeline.md` 的脱敏清单。

## 四条硬规矩

违反任一条，这一镜重做。

1. **数字带口径。** 说 499 之前先说"节点含根文件 project.cbm"；说 779 之前先说"一条键算一条边"。口径写在画面上（底部小字），不只靠嘴说。
2. **结论带边界。** 六个样本五份同源，就说"这个导出端在六份之间一致"，不说"所有 GIM 实现都这样"。
3. **标准带出处。** 每条引用标到条文号或表号（§7.2 / 表 A.1 / 表 C.24）。
4. **实例只放真的。** 文件全文照抄，行数标在角上；脱敏要注明"已偏移脱敏"，让观众知道处理过。

## 常犯的三个错

**把工程特征说成标准规定。** "每个耐张段挂 11 个设备组"——错，11 是这一段的塔数+档数×相数+跨越数，换个工程就变。标准只规定结构和职责，不规定数量。

**用示意图冒充真实内容。** 画一个圆点树说"这就是层级"——观众会当成真的。要么贴真实截图，要么明确标"示意"。

**三处用词不一致。** 章名叫"设备"、页标题写"实体"、口播说"最小单元"，单看每处都对，合起来让人困惑。定稿前把章名/页标题/口播三列对齐一遍。

## 命令速查

| 要做的事 | 命令 |
|---|---|
| 出静帧 | `python scripts/check_frames.py 3,7` |
| 只看一镜重渲 | 删该镜 mp4 → `render_segment(i, aud)` → `make_video.py --remux` |
| 出分镜稿 | `python scripts/make_shotlist.py` |
| 出封面 | `python scripts/make_cover.py` |
| 重建 notebook | `python scripts/build_ipynb.py`（从 tutorial.py 切段，不手抄） |
| 查坐标残留 | `grep -rn "28\.24\|113\.14" --include=*.py --include=*.slide .` |

## 环境前提

- **双 Python**：bash 默认 `python` 无三方库；用 `C:/Users/Lenovo/AppData/Local/Programs/Python/Python313/python.exe`
- 依赖：Pillow、edge-tts、nbformat、nbclient；外部 `ffmpeg` / `ffprobe` 在 PATH
- 幻灯片用 slidep CLI（`slidep upsert-dsl` / `screenshot` / `inspect` / `lint`）
- TTS 需联网（edge-tts 走微软接口）

## 细节索引

- 配色、字号、七种组件 → `references/visual-system.md`
- 五章模板、句法、词汇、读音 → `references/narrative.md`
- 五步流程、缓存、拼接原理 → `references/pipeline.md`
- 18 个真实坑（含代码级报错）→ `references/pitfalls.md`
- EP01 具体怎么排的 29 页、六轮改了什么 → `references/ep01-structure.md`
- 完整渲染实现 → `templates/make_video_reference.py`
- 单页 DSL 写法 → `templates/page.slide`
