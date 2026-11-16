# 第 8 周 · 互评记录

- 评阅人：陈子妍（f25210103）
- 评阅对象：吴晨阳（f25210238）
- 对象仓库：<https://gitee.com/f25210238/homework>（仓库名「作业」，分支 master，W8 内容在 `w8/`）
- 评阅时间：2026-11-16 19:00 左右
- 结论一句话：**README 写得完整、已知问题很诚实，但按原仓库**跑不起来**——缺 `weekpath.py`，补上之后又缺 `llm`；也没有发 Release。**

## 我实际做的（照着 README「怎么装 / 怎么用」走）

环境：Windows 11 · Python 3.12 · Ollama 已装（`qwen2.5:0.5b`、`nomic-embed-text` 均在）；`qwen2.5:7b-instruct` 未装（拉取失败）。

1. 把仓库下载成 ZIP 解压，进入 `w8/` 目录
2. 按 README「怎么用」第一条执行 `python assistant_v1.py`
3. 报错后，按 README「怎么装」检查依赖，再试一次

## 四维度记录（只写现象）

| 维度 | 我看到的实际情况 |
|---|---|
| 1 能不能跑 | **不能（实测）**。第一次：`ModuleNotFoundError: No module named 'weekpath'`——仓库根目录没有 `weekpath.py`。我手工补了一个 `weekpath.py` 再跑：`ModuleNotFoundError: No module named 'llm'`——`llm.py` 在 `w6/`、`rag_qa.py` 在 `W7/`，都不在 `import` 能找的路径上。`assistant_v1.py` 里 `ROOT = 仓库根`，但根目录确实没有这两个模块。 |
| 2 README 能复现吗 | **部分能**：四段式（功能/怎么装/怎么用/已知问题）齐全，命令写得清楚。但「怎么装」第一条 `pip install -r requirements.txt` 无处可执行——`w8/` 目录里没有 `requirements.txt`；README「相关交付」提到的 `known_issues.md`、`reflect.md`、`release_notes.md` 在 `w8/` 里也没看到。按 README 走到第 2 条就断在 import。 |
| 3 Release 发了吗 | **没有**。仓库右侧显示「发行版：暂无发行版」、`标签 0`。README 里「发布 v1.0」只给了 `git tag`/`git push --tags` 的命令，不等于已经发过。 |
| 4 有没有已知限制 | **有，而且写得比要求更细**。4 条：没 key 时 `--prefer api` 会明确报错（不假装成功）、`nomic-embed-text` 中文排序有噪声（提醒看出处与 top-2~4 段）、7b 首次加载慢、换文本必须 `rag_qa.py --rebuild`。这一项是本项目最好的部分。 |

## 补充说明

- 我**没有继续替他补文件**：把 `llm.py`、`rag_qa.py` 搬进根目录属于改对方代码，超出“照着 README 复现”的范围；所以①的结论停在“按原仓库跑不通”。
- 他的 `w8/` 文件是 19–36 分钟前才补上的，**本记录以 19:00 的仓库状态为准**；若之后补了 `weekpath.py`、`requirements.txt` 并发了 Release，结论会变，可以再评一次。

## 我做的步骤（供核对）

1. 打开 <https://gitee.com/f25210238/homework>，确认 `w8/` 有 README.md、answer_log.md、assistant_v1.py、pipeline_mapping.md
2. 下载 ZIP → 解压 → `cd w8` → `python assistant_v1.py` → 报 `No module named 'weekpath'`
3. 在仓库根补 `weekpath.py` → 再跑 → 报 `No module named 'llm'`
4. 查看仓库右侧：`标签 0`、「暂无发行版」
5. 通读 README 四段与「发布 v1.0」「相关交付」两节

按《第8周指定互评分配表》纪律：只描述现象、不打分、不评价人。
