# -*- coding: utf-8 -*-
"""从 tutorial.py 按 Step 注释切段，生成 tutorial.ipynb。

前置：本脚本在 tutorial.py 所在目录执行。
用法：python build_ipynb.py
输出：./tutorial.ipynb（24 格）

为什么不用手抄：手抄一份代码，tutorial.py 一改 notebook 就过期。
切段生成保证两边永远同步。

坑：config 单元不能搬命令行解析——ipykernel 的 sys.argv 带 "-f kernel.json"，
会把 ROOT 覆盖成 "-f"。只取常量本身。
"""
import json
import os
import re

SRC = 'tutorial.py'
OUT = 'tutorial.ipynb'

src = open(SRC, encoding='utf-8').read()

# ---- 切：CONFIG（含命令行参数） / 小工具 / 十步 ----
i_cfg = src.index('# ================================================================ CONFIG')
i_tool = src.index('# ================================================================ 小工具')
i_step1 = src.index('# ---------------------------------------------------------------- Step 1')
i_steps = src.index('STEPS = [')

# notebook 里不能照抄命令行参数解析：ipykernel 的 sys.argv 带着 -f kernel.json，
# 会把 ROOT 覆盖成 '-f'。所以只取 CONFIG 常量本身。
i_cli = src.index('# 命令行可临时覆盖')
config = ('import os\nimport re\nimport sys\nimport glob\nimport struct\n'
          'import collections\n\n' + src[i_cfg:i_cli].rstrip()
          + '\n\nif not ROOT:\n'
            "    print('（还没填 ROOT：Step 1 可以只填 GIM；Step 2 起需要解包目录）')")
tools = src[i_tool:i_step1].rstrip()

steps = []
for n in range(1, 11):
    a = src.index(f'# ---------------------------------------------------------------- Step {n}')
    b = (src.index(f'# ---------------------------------------------------------------- Step {n + 1}')
         if n < 10 else i_steps)
    steps.append(src[a:b].rstrip())

MD_INTRO = """# 线路 GIM 文件拆解（新手向 · notebook 版）

与同目录 `tutorial.py` **同一份源码**：本 notebook 由 `build_ipynb.py` 从脚本切段生成，
可以一格一格跑、随时停下来看中间结果。步骤划分与《线路GIM文件拆解.pptx》29 页五章对应
（每步标题后面标了页码）。

## 开始前只做一件事：在下一格填 `ROOT`

- `ROOT`：解包后的 GIM 目录，里面能看到 `Cbm / Dev / Phm / Mod`
- `GIM`：`.gim` 原包路径，只有 Step 1 读容器头需要；**只看头时可以只填 GIM**

不知道怎么解包？用 `01-样本分析/教程案例/gim_unpack.py` 处理一次 `.gim` 原包即可。

> **口径**：节点 = cbm 文件（含根文件 `project.cbm`）；边 = 父 cbm 里"值以 `.cbm` 结尾
> 且键不以 `.NUM` 结尾"的键，一条键算一条边；多父 = 同一节点被两个及以上父节点引用。
> 本 notebook 的示例数字来自教学样本 line04（499 个节点 / 779 条边），换样本会变。
"""


def cell(kind, text, cid):
    c = {'cell_type': kind, 'id': cid, 'metadata': {},
         'source': text.splitlines(keepends=True)}
    if kind == 'code':
        c.update({'execution_count': None, 'outputs': []})
    return c


cells = [cell('markdown', MD_INTRO, 'intro'),
         cell('code', '# === 第 0 格 · CONFIG：填你的样本位置 ===================================\n'
                      + config, 'config'),
         cell('code', '# === 工具函数（与脚本同一份）==========================================\n'
                      + tools, 'tools')]

for n, body in enumerate(steps, start=1):
    m = re.search(r"banner\((\d+),\s*'([^']+)',\s*'([^']+)'\)", body)
    title, page = (m.group(2), m.group(3)) if m else (f'Step {n}', '')
    fn = re.search(r'^def (step\d+_\w+)\(', body, re.M).group(1)
    md = f'## Step {n} · {title}（PPT {page}）\n\n> 代码与 `tutorial.py` 的 `{fn}()` 完全一致。'
    cells.append(cell('markdown', md, f'md{n}'))
    cells.append(cell('code', body + f'\n\n\n{fn}()', f'code{n}'))

cells.append(cell('markdown', """## 跑完之后

三条能立刻用上的判据：

1. **节点与边**：`499` / `779` 这种数字只在"含根文件、按键计边"的口径下成立；换口径数字就变。
2. **多父**：入度分布才是事实，不要用"两个父亲"概括。
3. **FAM**：`BASEFAMILY` 可为空、F3 级有 1~4 个槽位——按指针关联，不要假定一对一。
""", 'outro'))

nb = {
    'cells': cells,
    'metadata': {
        'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
        'language_info': {'name': 'python', 'version': '3.13'},
    },
    'nbformat': 4,
    'nbformat_minor': 5,
}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print(f'{OUT}: {len(cells)} cells, {os.path.getsize(OUT)} bytes')
