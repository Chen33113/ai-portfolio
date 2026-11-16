# week09_工具调用

W9 当堂交付：**一个能自主调 3 个工具的 `tool_agent.py` + 3 条调用轨迹**。

## 文件

| 文件 | 用途 |
|---|---|
| `tool_agent.py` | 主程序：4 个工具 + JSON 解析 + 最多 3 轮的「决定→执行→回喂」循环 + 强制收口 |
| `call_trace.md` | **要交的轨迹记录**：3 条完整轨迹 + 3 个失败案例会诊 |
| `../data/生词表.csv` | 词表（词汇/等级/词性/例句），`hsk_level` 与 `text_difficulty` 都读它 |

## 4 个工具

| 工具 | 输入 | 输出 |
|---|---|---|
| `get_time` | 无 | 当前时间字符串 |
| `calc` | 一个表达式字符串，如 `"35*24"` | 结果；非白名单语法返回「拒绝计算」 |
| `hsk_level` | 一个词，如 `"把"` | 「把 是 3 级」或「未找到」 |
| `text_difficulty` | 一段课文 + 目标等级（默认 4） | JSON：总字数 / 覆盖字数 / 生词覆盖率 / 超纲词列表 |

`calc` 用**白名单 AST**（只放行数字与 `+ - * / ** %`），**没有用 eval**——`eval` 能执行任意代码、读到 `.env` 里的密钥，是课程红线。

## 跑

```powershell
# 有云端 key
$env:DEEPSEEK_API_KEY="你的key"
python tool_agent.py

# 没有 key，走本机 Ollama（本次演示就是这样跑的）
$env:DEEPSEEK_BASE_URL="http://localhost:11434/v1"
$env:DEEPSEEK_MODEL="qwen2.5:0.5b"
python tool_agent.py "「把」字是 HSK 几级？"
```

## 已知问题

- **本机 0.5B 会反复点名同一个工具**：靠 `max_calls=3` + 收口兜住，轨迹里能看到重复调用；换云端或更大的本地模型会稳很多。
- **复合问句最容易翻车**：模型常只查一件事就收口，收口时我把已查到的结果摊开回喂，才逼出完整答案。
- **`text_difficulty` 不做分词**：用「生词表里的词是否出现在课文中」做粗匹配，覆盖率是近似值，够教学初筛用。
