# 第 9 周 · smolagents 对照（5 行映射表）

> 全员最低要求。左边是我手写的 `tool_agent.py`，右边是 huggingface/smolagents 的 `ToolCallingAgent`。
> 许可证：Apache-2.0（可阅读、可学思路、需署名）；我**没有复制它的代码**，只对照结构。

| # | 我写的 `tool_agent.py` | smolagents 里对应什么 |
|---|---|---|
| 1 | `TOOLS` 字典：名字 → 函数（`{"hsk_level": hsk_level, ...}`） | `@tool` 装饰器把带类型注解和 `Args:` 文档的函数变成 `Tool`，再交给 `ToolCallingAgent(tools=[...])` |
| 2 | `SYS` 提示词要求模型只输出一行 JSON | `ToolCallingAgent` 用模型原生的 tool calling（JSON-like），提示模板在 `prompts/toolcalling_agent.yaml` |
| 3 | `parse_calls()`：剥 ```json 围栏、`re.S` 跨行抓块、正则兜底 | 框架内部解析 `ChatMessageToolCall`，不用自己写正则 |
| 4 | `TOOLS[name](*args)` 执行 + 异常兜底，结果拼成「工具返回：…」 | 框架按 `Tool.inputs` 校验参数后调用，结果自动进入多步消息 |
| 5 | `run()` 手动回喂 + `max_calls` 收口 | `MultiStepAgent` 的多步循环由框架管理步数与停止条件 |

## 一句话

框架替我做掉的是**解析、校验、循环管理**这三件苦力活；它拿走的是**「模型到底决定调什么」的可见性**——都藏在抽象层里。所以先手写一遍再看框架，才知道自己省了什么、又失去了什么控制权。

## 我的判断

我这 60 行的价值不在“能跑”，在于**每个失败都能定位**：模型输出坏了是 `parse_calls` 的问题、参数错了是 `run()` 校验的问题、停不下来是 `max_calls` 的问题。换成框架之后，这些位置都变成“框架内部”——出问题只能看日志。对小项目，手写更透明；工具一多、要接外部服务，才该上框架（也就是 W10 的 MCP 要解决的事）。
