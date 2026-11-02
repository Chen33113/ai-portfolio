#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W6 · 双引擎封装：对外只有一个入口 ``llm.ask()``（多轮用 ``llm.chat()``）。

用法::

    from llm import ask, LLM

    ask("用一句话解释潮汐是怎么来的")                  # 默认 prefer="local"
    ask("用一句话解释潮汐是怎么来的", prefer="api")    # 直接走云端
    ask("用一句话解释潮汐是怎么来的", prefer="local")  # 本地挂了会自动切云端

    bot = LLM(prefer="local")            # 多轮：同一个实例记住上下文
    bot.chat("我下周要讲 HSK4《愚公移山》")
    bot.chat("刚才说的那篇课文，帮我出 3 道判断题")   # 它知道“那篇”是哪篇
    bot.reset()                          # 换话题，清空记忆

命令行::

    python llm.py "用一句话解释潮汐是怎么来的"
    python llm.py --prefer api "..."
    python llm.py --chat                 # 进多轮对话（:reset 清空，:q 退出）
    python llm.py --selftest             # 两个引擎各探一次

封装的三条主线（和课堂上的三块一一对应）：

1. 两个引擎同一张脸 —— ``LocalEngine`` 和 ``APIEngine`` 都只暴露
   ``chat(messages) -> dict``，上层不关心底下是 HTTP 还是 SDK。
2. 按需创建客户端 —— 构造函数不碰网络，第一次 ``chat`` 才建连接/客户端；
   所以「Ollama 没开」不会在 import 的那一刻就炸。
3. 回退放在 LLM 层 —— 引擎只负责「我失败了」（抛 ``EngineError``），
   「谁来顶班」由 ``LLM`` 决定。以后加第三个引擎，两个引擎一行都不用改。

作业 1 选了「多轮对话」，理由（评分点就在这段注释里）：
    · 我的实际场景是备课，一句话很少能说清——「刚才那篇课文」「再短一点」这类
      指代必须靠 messages 里的上下文，单轮接口做不了，这是刚需；
    · 「失败重试」和「耗时/费用估算」属于横切能力，加在 LLM 层会污染两个引擎的
      统一接口；而且云端 SDK 自带重试、本地同机重试意义不大，性价比低于多轮；
    · 多轮只改「消息怎么攒」，不改「谁来答」，正好验证第 3 条主线：
      回退时整段 messages 一起交给备用引擎，上下文不丢。
    代价：多轮会让 token 线性增长，所以给了 ``max_history`` 上限，超了从最旧的
    一轮开始丢。

环境变量（都有默认值，可不填）::

    OLLAMA_HOST        本机 Ollama 地址，默认 http://127.0.0.1:11434
    LLM_LOCAL_MODEL    本地模型名，默认 qwen2.5:0.5b
    DEEPSEEK_API_KEY   云端 key；没有就一定会回退
    DEEPSEEK_BASE_URL  默认 https://api.deepseek.com
    LLM_API_MODEL      默认 deepseek-chat
    LLM_PREFER         默认 prefer，local 或 api
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_LOCAL_HOST = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5:0.5b"
DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_API_MODEL = "deepseek-chat"

Message = Dict[str, str]


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _log(message: str) -> None:
    """切换日志统一走 stderr，不污染 ask() 的正文输出。"""
    print(f"[llm] {message}", file=sys.stderr, flush=True)


def _as_messages(prompt_or_messages: Any) -> List[Message]:
    """一个字符串 = 单轮；一串 messages = 多轮。两个引擎都吃这一种输入。"""
    if isinstance(prompt_or_messages, str):
        return [{"role": "user", "content": prompt_or_messages}]
    return [dict(item) for item in prompt_or_messages]


class EngineError(RuntimeError):
    """引擎层唯一异常：说清是谁挂的、为什么挂。"""

    def __init__(self, engine: str, reason: str) -> None:
        super().__init__(f"{engine}: {reason}")
        self.engine = engine
        self.reason = reason


class AllEnginesFailed(RuntimeError):
    """两个引擎都挂了。带上一路攒下来的失败原因，方便排错。"""

    def __init__(self, failures: List[Tuple[str, str]]) -> None:
        detail = "；".join(f"{name} → {reason}" for name, reason in failures)
        super().__init__(f"两个引擎都没答上来：{detail}")
        self.failures = failures


@dataclass
class Answer:
    """一次问答的完整账本：谁答的、多久、有没有回退、有没有被截断。"""

    text: str
    engine: str
    model: str
    elapsed: float
    prefer: str
    fell_back: bool = False
    reason: str = ""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    truncated: bool = False

    def __str__(self) -> str:
        return self.text

    def summary(self) -> str:
        tokens = ""
        if self.completion_tokens is not None:
            tokens = f"，completion_tokens={self.completion_tokens}"
        back = "（已回退）" if self.fell_back else ""
        cut = "，⚠ 输出被 max_tokens 截断" if self.truncated else ""
        return f"引擎={self.engine}{back} 模型={self.model} 耗时={self.elapsed:.2f}s{tokens}{cut}"


def _describe_url_error(exc: urllib.error.URLError) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ConnectionRefusedError):
        return "连接被拒绝（Ollama 没在运行？先 `ollama serve` 或点开羊驼图标）"
    if isinstance(reason, TimeoutError):
        return "连接超时（首次加载模型较慢，可调大 timeout）"
    return f"网络错误：{reason}"


def _describe_api_error(exc: Exception) -> str:
    """openai SDK 的异常类型很多，这里按类名收口成一句人话。"""
    mapping = {
        "AuthenticationError": "key 不对或已失效（401）",
        "PermissionDeniedError": "key 没有该模型的权限（403）",
        "RateLimitError": "被限流或余额不足（429）",
        "NotFoundError": "模型名不对（404）",
        "APITimeoutError": "请求超时",
        "APIConnectionError": "连不上 api.deepseek.com（网络/代理）",
        "BadRequestError": "请求被拒（400）",
    }
    name = type(exc).__name__
    raw = " ".join(str(exc).split())
    detail = raw if len(raw) <= 110 else raw[:110] + "…"
    return f"{mapping.get(name, name)}：{detail}" if detail else mapping.get(name, name)


class LocalEngine:
    """Ollama 的 /api/chat 直连，只用标准库（W5 的 http 直连搬过来）。"""

    name = "local"

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> None:
        host = host or _env("OLLAMA_HOST", DEFAULT_LOCAL_HOST)
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        self.host = host.rstrip("/")
        self.model = model or _env("LLM_LOCAL_MODEL", DEFAULT_LOCAL_MODEL)
        self.temperature = temperature
        self.timeout = timeout
        self._opener: Optional[urllib.request.OpenerDirector] = None

    def _get_opener(self) -> urllib.request.OpenerDirector:
        # 按需创建：构造函数不发请求，第一次 chat 才建 opener。
        if self._opener is None:
            # 关键：访问本机要关掉系统代理，否则 localhost 也会被送去代理
            self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return self._opener

    def chat(self, prompt_or_messages: Any, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        options: Dict[str, Any] = {"temperature": self.temperature}
        if max_tokens:
            # Ollama 里叫 num_predict；调小就会看到 done_reason="length"
            options["num_predict"] = int(max_tokens)
        payload = {
            "model": self.model,
            "messages": _as_messages(prompt_or_messages),
            "stream": False,
            "options": options,
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with self._get_opener().open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise EngineError(
                self.name, f"Ollama 返回 HTTP {exc.code}（多半是模型名写错，`ollama list` 看一下）"
            ) from exc
        except urllib.error.URLError as exc:
            raise EngineError(self.name, _describe_url_error(exc)) from exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise EngineError(
                self.name, f"连不上本机 Ollama（{self.host}）：{type(exc).__name__}"
            ) from exc
        elapsed = time.perf_counter() - started

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EngineError(self.name, "Ollama 返回的不是 JSON") from exc

        text = (data.get("message") or {}).get("content", "").strip()
        if not text:
            raise EngineError(self.name, "Ollama 返回了空回答")
        return {
            "text": text,
            "elapsed": elapsed,
            "model": data.get("model") or self.model,
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
            "truncated": data.get("done_reason") == "length",
        }


class APIEngine:
    """DeepSeek 的 OpenAI 兼容接口（W4 的调用方式搬过来）。"""

    name = "api"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else _env("DEEPSEEK_API_KEY")
        self.base_url = base_url or _env("DEEPSEEK_BASE_URL", DEFAULT_API_BASE)
        self.model = model or _env("LLM_API_MODEL", DEFAULT_API_MODEL)
        self.temperature = temperature
        self.timeout = timeout
        self._client: Any = None

    def _get_client(self) -> Any:
        # 按需创建：没有 key 就直接说清楚，别等 SDK 报一堆栈。
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise EngineError(self.name, "没有配置 DEEPSEEK_API_KEY")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EngineError(self.name, "没装 openai（pip install openai）") from exc
        # max_retries=0：失败要立刻回退，别让 SDK 自己默默重试三遍
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )
        return self._client

    def chat(self, prompt_or_messages: Any, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        client = self._get_client()
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": _as_messages(prompt_or_messages),
            "temperature": self.temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = int(max_tokens)
        started = time.perf_counter()
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:  # openai 的异常体系较杂，统一收口成 EngineError
            raise EngineError(self.name, _describe_api_error(exc)) from exc
        elapsed = time.perf_counter() - started

        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            raise EngineError(self.name, "云端返回了空回答")
        usage = getattr(response, "usage", None)
        return {
            "text": text,
            "elapsed": elapsed,
            "model": getattr(response, "model", self.model),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "truncated": choice.finish_reason == "length",
        }


class LLM:
    """统一入口：选顺序、调引擎、兜住异常、记日志、管多轮上下文。"""

    def __init__(
        self,
        prefer: str = "local",
        *,
        local: Optional[LocalEngine] = None,
        api: Optional[APIEngine] = None,
        verbose: bool = True,
        max_history: int = 12,
    ) -> None:
        self.prefer = prefer
        self.local = local or LocalEngine()
        self.api = api or APIEngine()
        self.verbose = verbose
        self.max_history = max(2, max_history)
        self.history: List[Message] = []
        self.last_switch: List[str] = []

    def _say(self, message: str) -> None:
        if self.verbose:
            _log(message)

    @staticmethod
    def _order(prefer: str) -> List[str]:
        # 双向回退：谁能先答就谁先，另一个永远是备胎。
        return ["local", "api"] if prefer == "local" else ["api", "local"]

    def reset(self) -> None:
        """换话题时清空记忆，避免旧上下文把新问题带偏。"""
        self.history.clear()

    def ask(
        self,
        prompt: str,
        prefer: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Answer:
        """单轮问答：不读写 history，问完就忘。"""
        return self._run([{"role": "user", "content": prompt}], prefer, max_tokens)

    def chat(
        self,
        prompt: str,
        prefer: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Answer:
        """多轮对话：把这一问接在 history 后面，答完再把回答接回去。"""
        self.history.append({"role": "user", "content": prompt})
        self._trim()
        answer = self._run(self.history, prefer, max_tokens)
        self.history.append({"role": "assistant", "content": answer.text})
        self._trim()
        return answer

    def _trim(self) -> None:
        """上下文太长就丢最旧的（system 消息永远保留）。"""
        if len(self.history) <= self.max_history:
            return
        system = [m for m in self.history if m["role"] == "system"]
        rest = [m for m in self.history if m["role"] != "system"]
        self.history = system + rest[-(self.max_history - len(system)):]

    def _run(
        self,
        messages: Sequence[Message],
        prefer: Optional[str],
        max_tokens: Optional[int],
    ) -> Answer:
        prefer = (prefer or self.prefer or "local").strip().lower()
        if prefer not in ("local", "api"):
            raise ValueError(f"prefer 只能是 'local' 或 'api'，收到 {prefer!r}")
        if not messages or not str(messages[-1].get("content", "")).strip():
            raise ValueError("prompt 不能为空")

        order = self._order(prefer)
        self.last_switch = []
        self._say(f"prefer={prefer}，尝试顺序：{' → '.join(order)}")

        failures: List[Tuple[str, str]] = []
        for index, name in enumerate(order):
            engine: Any = self.local if name == "local" else self.api
            try:
                result = engine.chat(messages, max_tokens=max_tokens)
            except EngineError as exc:
                failures.append((name, exc.reason))
                self._say(f"✖ {name} 引擎失败：{exc.reason}")
                if index == 0:
                    line = f"→ 自动回退到 {order[1]}（{name} 不可用）"
                    self.last_switch.append(line)
                    self._say(line)
                else:
                    self._say("✖ 备用引擎也失败，这次确实没有答案")
                continue

            if index > 0:
                line = f"✔ 回退成功：由 {name} 接管（原本想走 {failures[0][0]}）"
                self.last_switch.append(line)
                self._say(line)

            cut = "（输出被截断）" if result.get("truncated") else ""
            self._say(f"✔ 引擎={name} 模型={result['model']} 耗时={result['elapsed']:.2f}s{cut}")
            return Answer(
                text=result["text"],
                engine=name,
                model=result["model"],
                elapsed=result["elapsed"],
                prefer=prefer,
                fell_back=index > 0,
                reason=failures[0][1] if failures else "",
                prompt_tokens=result.get("prompt_tokens"),
                completion_tokens=result.get("completion_tokens"),
                truncated=bool(result.get("truncated")),
            )

        raise AllEnginesFailed(failures)


_default_llm: Optional[LLM] = None


def get_llm(**kwargs: Any) -> LLM:
    """拿默认实例；传参数则新建一个（测试和实验里常用）。"""
    global _default_llm
    if kwargs or _default_llm is None:
        _default_llm = LLM(**kwargs)
    return _default_llm


def ask(prompt: str, prefer: Optional[str] = None, max_tokens: Optional[int] = None) -> Answer:
    """程序的唯一入口。返回 Answer；print(它) 就是正文。"""
    return get_llm().ask(prompt, prefer, max_tokens)


def selftest() -> int:
    """两个引擎各探一次：只看「通不通」，不问「答得好不好」。"""
    ok = True
    for engine in (LocalEngine(), APIEngine()):
        try:
            result = engine.chat("你好，只回复两个字：收到")
            reason = ""
        except EngineError as exc:
            ok = False
            result, reason = None, exc.reason
        if result:
            print(f"{engine.name:<5} ✔ {result['elapsed']:5.2f}s  {result['model']}  「{result['text'][:24]}」")
        else:
            print(f"{engine.name:<5} ✖ {reason}")
    return 0 if ok else 1


def repl(llm: LLM) -> int:
    """--chat：多轮对话的小终端。:reset 清空，:q 退出。"""
    print("多轮对话已开启（:reset 清空上下文，:q 退出）", file=sys.stderr)
    while True:
        try:
            prompt = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr)
            return 0
        if not prompt:
            continue
        if prompt in (":q", ":quit", ":exit"):
            return 0
        if prompt == ":reset":
            llm.reset()
            print("（上下文已清空）", file=sys.stderr)
            continue
        try:
            answer = llm.chat(prompt)
        except AllEnginesFailed as exc:
            print(f"两个引擎都没能回答：\n  {exc}", file=sys.stderr)
            continue
        print(answer.text)
        print(f"  [{answer.summary()}]", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="W6 双引擎封装：一个入口 llm.ask()")
    parser.add_argument("prompt", nargs="?", help="要问的问题")
    parser.add_argument("--prefer", choices=("local", "api"), default=_env("LLM_PREFER", "local"))
    parser.add_argument("--selftest", action="store_true", help="两个引擎各探一次")
    parser.add_argument("--chat", action="store_true", help="进入多轮对话")
    parser.add_argument("--max-tokens", type=int, default=None, help="限制输出长度（看截断用）")
    parser.add_argument("--quiet", action="store_true", help="不打印切换日志")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    llm = LLM(prefer=args.prefer, verbose=not args.quiet)
    if args.chat:
        return repl(llm)
    if not args.prompt:
        parser.error("要么给一个问题，要么加 --selftest / --chat")

    try:
        answer = llm.ask(args.prompt, max_tokens=args.max_tokens)
    except AllEnginesFailed as exc:
        print(f"两个引擎都没能回答：\n  {exc}", file=sys.stderr)
        return 1

    print(answer.text)
    print(answer.summary(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
