#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W9 · tool_agent.py —— 让模型自己决定「下一步调哪个工具」。

    W8：use_rag=True 就先检索 —— 决定权在程序员的 if 里
    W9：问「『把』字几级？现在几点？」—— 决定权交给模型

一次调用是四步接力，模型不执行任何东西：

    1 提出：用户问
    2 决定：模型只输出 {"tool": "hsk_level", "args": ["把"]}
    3 执行：我们的 Python 函数去查 CSV / 算数 / 读时间
    4 回喂：把结果塞回消息，模型再生成最终回答

三个工具：get_time / calc（白名单 AST，绝不用 eval）/ hsk_level。

用法（从 week09_工具调用 目录）：

    python tool_agent.py                                  # 跑三条演示问句
    python tool_agent.py "「把」字是 HSK 几级？现在几点？"   # 单问

引擎：默认走 DeepSeek 云端；没有 key 时可指向本机 Ollama：

    $env:DEEPSEEK_BASE_URL="http://localhost:11434/v1"
    $env:DEEPSEEK_MODEL="qwen2.5:0.5b"
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime
import json
import operator
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import weekpath  # noqa: E402  跨周 import + 读 .env

weekpath.load_env()

from openai import OpenAI  # noqa: E402

MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def _vocab_path() -> str:
    """生词表放哪都行：优先根目录 data/，退而求其次找同目录（两种都兼容）。"""
    candidates = [
        weekpath.root_path("data", "生词表.csv"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "生词表.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


VOCAB = _vocab_path()

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY") or "ollama",  # 本机 Ollama 不校验 key
            base_url=BASE_URL,
            timeout=120,
            max_retries=0,
        )
    return _client


# ---------------------------------------------------------------- 三个工具

def get_time() -> str:
    """查当前时间，无参数。"""
    return str(datetime.datetime.now())


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("只允许数字与 + - * / ** % 运算")


def calc(expr) -> str:
    """白名单 AST 计算器。为什么不用 eval？eval 会执行任意代码，能读到文件和密钥。"""
    try:
        return str(_eval_node(ast.parse(str(expr), mode="eval")))
    except ZeroDivisionError:
        return "错误：除数为 0"
    except Exception as exc:  # noqa: BLE001
        return "拒绝计算：%s" % exc


def hsk_level(word) -> str:
    """查生词表 CSV 里词语的 HSK 等级。"""
    with open(VOCAB, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["词汇"].strip() == str(word).strip():
                return "%s 是 %s 级" % (word, row["HSK等级"])
    return "未找到 %s" % word


def _vocab() -> dict:
    with open(VOCAB, encoding="utf-8") as handle:
        return {row["词汇"].strip(): int(row["HSK等级"]) for row in csv.DictReader(handle)}


def text_difficulty(text, level=4) -> str:
    """课文难度评估：以生词表为词典，算生词覆盖率与超纲词。

    输入：一段课文 + 目标等级（默认 HSK4）
    输出：JSON 字符串，含总字数、覆盖字数、覆盖率、超纲词列表
    说明：用「生词表里的词是否出现在课文中」做粗匹配，不做分词；够教学初筛用。
    """
    text = str(text)
    vocab = _vocab()
    total = len(re.findall(r"[\u4e00-\u9fa5]", text)) or 1
    covered = 0
    over = []
    for word, word_level in vocab.items():
        count = text.count(word)
        if not count:
            continue
        covered += len(word) * count
        if word_level > int(level):
            over.append("%s(%d级)" % (word, word_level))
    return json.dumps(
        {
            "目标等级": "HSK%d" % int(level),
            "总字数": total,
            "覆盖字数": min(covered, total),
            "生词覆盖率": round(min(covered, total) / total, 3),
            "超纲词": over,
        },
        ensure_ascii=False,
    )


TOOLS = {
    "get_time": get_time,
    "calc": calc,
    "hsk_level": hsk_level,
    "text_difficulty": text_difficulty,
}

SYS = (
    "你是国际中文助教。可用工具只有这 4 个：get_time（查当前时间，无参数）、"
    "calc（四则运算，如 calc('35*24')）、hsk_level（查生词 HSK 等级，如 hsk_level('把')）、"
    "text_difficulty（评估课文难度，参数是一段课文，如 text_difficulty('我今天很累')）。"
    '如需调用，只输出一行 JSON，格式：{"tool": "工具名", "args": [参数]}；'
    "示例（照抄格式，不要改动）："
    '{"tool": "hsk_level", "args": ["把"]}；'
    '{"tool": "calc", "args": ["35*24"]}；'
    '{"tool": "get_time", "args": []}。'
    "注意：calc 的参数是一个字符串表达式（如 \"35*24\"），不要拆成两个数字；"
    "一次只调用一个工具，绝不编造不存在的工具名；无需工具时直接回答。"
)


# ---------------------------------------------------------------- 解析

def parse_calls(txt: str):
    """容错解析：剥 ```json 围栏、抓跨行 JSON 块、支持多行并列的多个调用。"""
    s = (txt or "").strip().replace("```json", "").replace("```", "").strip()
    try:
        obj = json.loads(s)
        return [obj] if isinstance(obj, dict) else []
    except Exception:  # noqa: BLE001
        match = re.search(r"\{.*\}", s, re.S)
        if match:
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    return [obj]
            except Exception:  # noqa: BLE001
                pass
    calls = []
    for block in re.findall(r"\{[^{}]*\}", s):
        try:
            obj = json.loads(block)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict):
            calls.append(obj)
    if calls:
        return calls

    # 最后一道兜底：小模型偶尔把 JSON 写残（少一个 ] 或 }），用正则把工具名和参数抠出来
    name_match = re.search(r'"tool"\s*:\s*"([A-Za-z_]\w*)"', s)
    if not name_match:
        return []
    args_match = re.search(r'"args"\s*:\s*\[(.*?)(?:\]|\}|$)', s, re.S)
    args = []
    if args_match:
        raw = args_match.group(1)
        try:
            parsed = ast.literal_eval("[" + raw + "]")
            args = parsed if isinstance(parsed, list) else [parsed]
        except Exception:  # noqa: BLE001
            args = [part.strip().strip('"') for part in raw.split(",") if part.strip()]
    return [{"tool": name_match.group(1), "args": args}]


# ---------------------------------------------------------------- 主循环

def run(user_msg: str, max_calls: int = 3, verbose: bool = True) -> str:
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": user_msg}]
    facts = []  # 攒下每次工具返回，收口时原样塞回去，避免小模型漏答
    for _ in range(max_calls):
        txt = get_client().chat.completions.create(
            model=MODEL, messages=msgs, temperature=0
        ).choices[0].message.content
        if verbose:
            print("[模型原始输出]", (txt or "").replace("\n", " ")[:160], file=sys.stderr)
        calls = [c for c in parse_calls(txt) if isinstance(c.get("tool"), str) and c.get("tool") in TOOLS]
        if not calls:
            return txt

        results = []
        for call in calls:
            args = call.get("args") or []
            if not isinstance(args, list):
                results.append("工具参数格式错误：%r" % (args,))
                continue
            try:
                value = TOOLS[call["tool"]](*args)
                results.append("%s%r → %s" % (call["tool"], args, value))
            except Exception as exc:  # noqa: BLE001
                results.append("工具执行失败：%s" % exc)
        if verbose:
            print("[工具返回]", "；".join(results), file=sys.stderr)
        facts.extend(results)

        msgs += [
            {"role": "assistant", "content": txt},
            {
                "role": "user",
                "content": "工具返回：%s。如果用户的问题里还有其他部分没查，继续只输出一行 JSON 调用下一个工具；"
                "如果没有别的要查了，就直接用一句自然语言回答用户，不要再输出 JSON。"
                % "；".join(results),
            },
        ]

    # 到上限强制收口：模型容易反复点名同一个工具（本机小模型尤其明显），
    # 这里把已查到的结果再摊开一次，逼它用一句自然语言把每一条都答到。
    # 小模型偶尔会复读 JSON 甚至复读我的指令，所以最多试三次、每次都换一种说法。
    variants = [
        "已知：%s。不要再输出 JSON，也不要再调用工具；请用一句中文回答，把上面每一条都答到。",
        "资料：%s。请直接说结论，一句话，中文，不要任何格式标记。",
        "请用中文回答用户的问题：%s。",
    ]
    text = ""
    for template in variants:
        msgs.append({"role": "user", "content": template % "；".join(facts)})
        text = get_client().chat.completions.create(
            model=MODEL, messages=msgs, temperature=0
        ).choices[0].message.content or ""
        bad = text.lstrip().startswith("{") or "不要再输出" in text or "禁止输出" in text
        if not bad:
            return text
    return text


DEMOS = [
    "「把」字是 HSK 几级词汇？",
    "35*24 等于多少？",
    "请依次查询两件事：1. 「把」字的 HSK 等级是多少？2. 现在的时间是多少？",
]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="W9 工具调用智能体")
    parser.add_argument("question", nargs="?", help="单个问题；不给就跑三条演示")
    args = parser.parse_args()

    questions = [args.question] if args.question else DEMOS
    for question in questions:
        print("Q:", question)
        try:
            print("A:", run(question))
        except Exception as exc:  # 没起 Ollama / 没 key 都不能让演示中断
            print("A: [运行失败] %s: %s" % (type(exc).__name__, exc))
        print("-" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
