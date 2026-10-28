# W6 双引擎封装 · 边界测试记录

- 测试时间：2026-10-26 13:53
- 环境：Windows 11 · Python 3.12 · Ollama 本机 · `qwen2.5:0.5b` · `deepseek-chat`
- 统一问题（同学科）：用两句话向 HSK4 学生解释「把」字句的用法，并给一个例句。
- 入口：`llm.ask(prompt, prefer=...)`；切换日志就是 stderr 里的 `[llm]` 行

## 一、测试记录（5组）

| # | ① 测试条件 | ② 实际走的引擎（切换日志） | ③ 耗时与答案质量点评 | ④ 是否符合预期 / 怎么改的 |
|---|---|---|---|---|
| ① 正常本地（Ollama 开） | Ollama 开 · prefer='local' | **local**（无切换） | 0.48s / 28 tok；0.5B 把「把」字句讲成「表示动作、结果、原因的句子结构」，定义不对（漏了“对受事施加处置”这一层），例句「他把书放在桌子上」是对的。 | 符合；本地这档只验链路，不追求 0.5B 的语法质量；质量对照看 ②③。 |
| ② 关掉 Ollama（自动回退云端） | 本地连不上 · prefer='local' | **api**（回退：自动回退到 api（local 不可用）） | 2.01s / 40 tok；云端定义准确（处置义 + 结构公式），例句自然，比本地强一个量级。 | 符合；改的是测试手段：本机 Ollama 由其他账户启动，普通权限结束不了进程，改用「本地地址指到空端口」制造连接被拒绝；异常类型与真关服务一致，日志原样保留。 |
| ③ 云端直连（prefer='api'） | prefer='api' | **api**（无切换） | 2.73s / 43 tok；与 ② 同模型同问题，答案几乎一字不差，说明 prefer='api' 是直连云端、没偷偷先试本地。 | 符合；无需改动。 |
| ④ 额外一组：本地模型名写错 | Ollama 开但模型名写错 · prefer='local' | **api**（回退：自动回退到 api（local 不可用）） | 2.22s / 51 tok；本地报 404 后 1 秒内切到云端，答案正常。 | 符合；这条证明回退不只认「连不上」，模型名写错也兜得住。 |
| ⑤ 额外一组：云端不可用（key 失效） | key 无效 · prefer='api' | **local**（回退：自动回退到 local（api 不可用）） | 0.8s / 51 tok；云端 401 后立刻回本地，有答案；但 0.5B 的解释明显不对，只证明链路没断。 | 符合；这条补上「云端挂 → 回本地」的反向验证，和 ②④ 合起来才是双向。 |

## 二、原始日志

### ① 正常本地（Ollama 开）

```text
[llm] prefer=local，尝试顺序：local → api
[llm] ✔ 引擎=local 模型=qwen2.5:0.5b 耗时=0.48s

--- 回答正文（qwen2.5:0.5b，0.48s）---
"把"字句是一种表示动作、结果、原因等关系的句子结构。例句：他把书放在桌子上。
```

### ② 关掉 Ollama（自动回退云端）

```text
[llm] prefer=local，尝试顺序：local → api
[llm] ✖ local 引擎失败：连接被拒绝（Ollama 没在运行？先 `ollama serve` 或点开羊驼图标）
[llm] → 自动回退到 api（local 不可用）
[llm] ✔ 回退成功：由 api 接管（原本想走 local）
[llm] ✔ 引擎=api 模型=deepseek-flash 耗时=2.01s

--- 回答正文（deepseek-flash，2.01s）---
「把」字句用来强调“对某个东西做了什么事”，基本结构是“主语 + 把 + 宾语 + 动词 + 其他成分”。例如：我把作业做完了。
```

### ③ 云端直连（prefer='api'）

```text
[llm] prefer=api，尝试顺序：api → local
[llm] ✔ 引擎=api 模型=deepseek-flash 耗时=2.73s

--- 回答正文（deepseek-flash，2.73s）---
「把」字句用来强调对某个东西做了什么事、产生了什么结果，基本结构是“主语 + 把 + 宾语 + 动词 + 其他成分”。例如：我把作业写完了。
```

### ④ 额外一组：本地模型名写错

```text
[llm] prefer=local，尝试顺序：local → api
[llm] ✖ local 引擎失败：Ollama 返回 HTTP 404（多半是模型名写错，`ollama list` 看一下）
[llm] → 自动回退到 api（local 不可用）
[llm] ✔ 回退成功：由 api 接管（原本想走 local）
[llm] ✔ 引擎=api 模型=deepseek-flash 耗时=2.22s

--- 回答正文（deepseek-flash，2.22s）---
「把」字句用来强调“对某个东西做了什么事”，基本结构是“主语 + 把 + 宾语 + 动词 + 其他成分”。它常用于表达动作对宾语产生的结果或影响。例句：我把作业做完了。
```

### ⑤ 额外一组：云端不可用（key 失效）

```text
[llm] prefer=api，尝试顺序：api → local
[llm] ✖ api 引擎失败：key 不对或已失效（401）：Error code: 401 - {'error': {'message': 'Authentication Fails, Your api key: ****test is invalid (request_id: …
[llm] → 自动回退到 local（api 不可用）
[llm] ✔ 回退成功：由 local 接管（原本想走 api）
[llm] ✔ 引擎=local 模型=qwen2.5:0.5b 耗时=0.80s

--- 回答正文（qwen2.5:0.5b，0.8s）---
"把"字句是一种表示动作或结果的动词短语，用来表示从属关系，表示动作或结果从主语处获得，或从非主语处获得。其例句：我把这本书放在桌子上。
```

## 三、复现命令

```powershell
python llm.py --selftest
python run_boundary_tests.py --only 1
python run_boundary_tests.py --only 2 --local-host http://127.0.0.1:11499
python run_boundary_tests.py --only 3
python run_boundary_tests.py --only 4
python run_boundary_tests.py --only 5
```

## 四、结论与改动

- **三条必做路径 + 两条额外路径**：① 0.48s 本地 → ② 2.01s 本地失败回退云端 → ③ 2.73s 云端直连；另外 ④ 模型名写错（404）回退、⑤ key 失效（401）回退，边角情况都落在日志里。
- **回退确实双向**：`prefer='local'` 时本地挂 → 云端（②④），`prefer='api'` 时云端挂 → 本地（⑤）。换方向只改 `prefer`，两个引擎的代码一行没动。
- **两处改动记录**：② 组「关掉 Ollama」用了等价做法——本机服务在别的账户下，普通权限杀不掉进程，于是把地址指到 `127.0.0.1:11499`（连接被拒绝，异常路径和真关服务一样）；⑤ 组故意用一个假 key，只为验 401 的回退，与真实 key 无关。
- **模型名对不上是正常的**：请求写 `deepseek-chat`，响应里 `model` 是 `deepseek-flash`，说明这个 key 当前被平台路由到 flash 版本；代码里 `model` 取的是响应值，所以日志显示的是实际模型。
- **结论**：封装的收益是「调用方只记 `ask()` + `prefer`」——本地/云端的差异、代理坑、404/401 都收在引擎里。0.5B 只够验证链路，真拿来做教学，本地得换 3B/7B，或者默认走云端。

