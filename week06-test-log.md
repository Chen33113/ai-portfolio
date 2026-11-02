# W6 双引擎封装 · 边界测试记录

- 测试时间：2026-11-02 13:01
- 环境：Windows 11 · Python 3.12 · Ollama 本机 · `qwen2.5:0.5b` · `deepseek-chat`
- 统一问题（同学科）：用两句话向 HSK4 学生解释「把」字句的用法，并给一个例句。
- 入口：`llm.ask(prompt, prefer=...)`；切换日志就是 stderr 里的 `[llm]` 行

## 一、测试记录（6 组，逐条对四列）

| # | ① 测试条件 | ② 实际走的引擎（切换日志） | ③ 耗时与答案质量点评 | ④ 是否符合预期 / 怎么改的 |
|---|---|---|---|---|
| ① 正常本地（Ollama 开） | Ollama 开 · prefer='local' | **local**（无切换） | 2.41s / 29 tok；0.5B 说「把字句是表示动作或行为的句子」，只碰对了「动词后要带结果」这一点，处置义完全没讲；例句「他把书放在桌子上」倒是对的。 | 符合；本地这档只验链路，不追求 0.5B 的语法质量；质量对照看 ②③。 |
| ② 关掉 Ollama（自动回退云端） | 本地连不上 · prefer='local' | **api**（回退：自动回退到 api（local 不可用）） | 1.9s / 50 tok；定义准确（处置义 + 结构公式），例句自然，比本地强一个量级。 | 符合；改的是测试手段：本机 Ollama 由其他账户启动，普通权限结束不了进程，改用「本地地址指到空端口」制造连接被拒绝；异常类型与真关服务一致，日志原样保留。 |
| ③ 云端直连（prefer='api'） | prefer='api' | **api**（无切换） | 1.92s / 56 tok；与 ② 同模型同问题，答案更细（补了「确定的事物」「结果」），说明 prefer='api' 是直连云端、没偷偷先试本地。 | 符合；无需改动。 |
| ④ 额外一组：本地模型名写错 | Ollama 开但模型名写错 · prefer='local' | **api**（回退：自动回退到 api（local 不可用）） | 1.78s / 54 tok；本地报 404 后 1 秒内切到云端，答案正常。 | 符合；这条证明回退不只认「连不上」，模型名写错也兜得住。 |
| ⑤ 额外一组：云端不可用（key 失效） | key 无效 · prefer='api' | **local**（回退：自动回退到 local（api 不可用）） | 0.55s / 30 tok；云端 401 后立刻回到本地；0.5B 这次把「把」字句说成「表示动作的执行者」，例句也跑题——正好说明隐私任务为什么宁可慢也要留本地。 | 符合；这条补上「云端挂 → 回本地」的反向验证，和 ②④ 合起来才是双向。 |
| ⑥ 额外一组：max_tokens 调小看截断 | prefer='api' · max_tokens=24 | **api**（无切换） | 1.13s / 24 tok，⚠ 被截断（finish_reason=length）；max_tokens=24 时在「基本结构是：主语」处被切断，finish_reason=length，日志里打了「输出被截断」。 | 符合；无需改动；截断不会被当成正常回答吞掉，Answer.truncated 会亮出来，才知道该调大 max_tokens 还是改提示词。 |

## 二、原始日志

### ① 正常本地（Ollama 开）

```text
[llm] prefer=local，尝试顺序：local → api
[llm] ✔ 引擎=local 模型=qwen2.5:0.5b 耗时=2.41s

--- 回答正文（qwen2.5:0.5b，2.41s）---
把字句是一种表示动作或行为的句子，表示一种动作或行为的完成。例句：他把书放在桌子上。
```

### ② 关掉 Ollama（自动回退云端）

```text
[llm] prefer=local，尝试顺序：local → api
[llm] ✖ local 引擎失败：连接被拒绝（Ollama 没在运行？先 `ollama serve` 或点开羊驼图标）
[llm] → 自动回退到 api（local 不可用）
[llm] ✔ 回退成功：由 api 接管（原本想走 local）
[llm] ✔ 引擎=api 模型=deepseek-flash 耗时=1.90s

--- 回答正文（deepseek-flash，1.9s）---
「把」字句用来强调“对某个东西做了什么”，基本结构是“主语 + 把 + 宾语 + 动词 + 其他成分”。它常用于表达动作对宾语产生的结果或影响。例句：我把作业写完了。
```

### ③ 云端直连（prefer='api'）

```text
[llm] prefer=api，尝试顺序：api → local
[llm] ✔ 引擎=api 模型=deepseek-flash 耗时=1.92s

--- 回答正文（deepseek-flash，1.92s）---
「把」字句用来强调“对某个确定的事物做了什么动作，以及动作的结果”。基本结构是：主语 + 把 + 宾语 + 动词 + 其他成分（如“了/完/好/在…”）。 例句：我把作业做完了。
```

### ④ 额外一组：本地模型名写错

```text
[llm] prefer=local，尝试顺序：local → api
[llm] ✖ local 引擎失败：Ollama 返回 HTTP 404（多半是模型名写错，`ollama list` 看一下）
[llm] → 自动回退到 api（local 不可用）
[llm] ✔ 回退成功：由 api 接管（原本想走 local）
[llm] ✔ 引擎=api 模型=deepseek-flash 耗时=1.78s

--- 回答正文（deepseek-flash，1.78s）---
「把」字句用来强调“对某个东西做了什么事”，基本结构是：主语 + 把 + 宾语 + 动词 + 其他成分。它通常用于表达对已知事物产生某种结果或影响的动作。例句：我把作业写完了。
```

### ⑤ 额外一组：云端不可用（key 失效）

```text
[llm] prefer=api，尝试顺序：api → local
[llm] ✖ api 引擎失败：key 不对或已失效（401）：Error code: 401 - {'error': {'message': 'Authentication Fails, Your api key: ****-401 is invalid (request_id: …
[llm] → 自动回退到 local（api 不可用）
[llm] ✔ 回退成功：由 local 接管（原本想走 api）
[llm] ✔ 引擎=local 模型=qwen2.5:0.5b 耗时=0.55s

--- 回答正文（qwen2.5:0.5b，0.55s）---
"把"字句是表示把某物交给某人或某物的结构。例句："他把信交给我。"
```

### ⑥ 额外一组：max_tokens 调小看截断

```text
[llm] prefer=api，尝试顺序：api → local
[llm] ✔ 引擎=api 模型=deepseek-flash 耗时=1.13s（输出被截断）

--- 回答正文（deepseek-flash，1.13s）---
「把」字句用来强调“对某个确定的事物做了什么动作，以及动作的结果”。基本结构是：主语
```

## 三、复现命令

```powershell
python llm.py --selftest
python run_boundary_tests.py --only 1
python run_boundary_tests.py --only 2 --local-host http://127.0.0.1:11499
python run_boundary_tests.py --only 3
python run_boundary_tests.py --only 4
python run_boundary_tests.py --only 5
python run_boundary_tests.py --only 6
```

## 四、结论与改动

- **六组测试**：① 本地直连 → ② 本地失败回退云端 → ③ 云端直连（必做三条）；④ 模型名写错（404）回退、⑤ key 失效（401）反向回退、⑥ max_tokens=24 触发截断（作业 2 要求的补充项）。
- **回退确实双向**：`prefer='local'` 时本地挂 → 云端（②④），`prefer='api'` 时云端挂 → 本地（⑤）。换方向只改 `prefer`，两个引擎一行没动。
- **作业 1 加了多轮对话**：`LLM.chat()` 维护 messages，`reset()` 清空，`max_history` 防上下文无限涨；回退时整段 messages 交给备用引擎，上下文不丢（② 组日志可见）。
- **改动记录**：② 组「关掉 Ollama」用等价做法（本机服务在别的账户下，普通权限杀不掉进程，把地址指到 `127.0.0.1:11499`，连接被拒绝的异常路径与真关一致）；⑤ 用假 key，只为验 401，与真实 key 无关。
- **模型名对不上是正常的**：请求写 `deepseek-chat`，响应里 `model` 是 `deepseek-flash`，平台把 chat 路由到 flash 版本；代码取响应值，所以日志显示实际模型。

## 五、反思（约 200 字）

什么任务固定走本地？凡是材料里有学生姓名、成绩、未公开教案的，一律本地。判断依据很朴素：数据一旦出机器就收不回来，慢一点、答得糙一点可以补救，泄露补不回来。什么任务固定走云端？语法讲解、出题、文化背景这类要求准确、要求成段的任务——0.5B 在这类问题上会一本正经地编（①⑤ 两组就是现成的反例），错了会直接教错学生。剩下「说不准」的和需要反复追问的备课任务，交给 `prefer` 让程序自己选：先本地，明显答偏再手动切云端。测试也给了量化依据：本地 0.47–2.41s、云端 1.13–1.92s，速度并没有拉开数量级，所以取舍主要看隐私和准确率，而不是谁快。

