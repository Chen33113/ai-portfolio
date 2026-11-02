#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W7 · RAG 最小实现：分块 → 向量化 → 检索 → 带资料回答。

对外接口和课堂骨架一致：

    get_retriever()            建库（分块 + 向量化）
    retrieve(question, k)      检索 top-k 片段
    rag_qa(question, prefer)   带资料回答（底层复用 W6 的 llm.LLM）
    ask_raw(question, prefer)  裸答（不给资料，用来做幻觉对照）

向量化有两条路，自动选：

1. 本机装了 `nomic-embed-text` → 调 Ollama `/api/embeddings` 拿神经向量；
2. 没装（比如 `ollama pull` 卡在 manifest）→ 用中文字符 bigram 的 TF-IDF 向量 + 余弦。
   纯标准库、断网可用，对小语料够用；对外仍然是「向量 + 余弦」，接口不变。

用法::

    python rag.py build                       # 建库，打印分块数
    python rag.py search "本课几个把字句"       # 只检索，看 top 段相不相关
    python rag.py ask "本课几个把字句"          # RAG 回答（默认云端）
    python rag.py ask "本课几个把字句" --raw    # 裸答，对照用
    python rag.py ask "本课几个把字句" --prefer local
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data.txt"
sys.path.insert(0, str(HERE.parent / "week06_双引擎"))

from llm import LLM, AllEnginesFailed  # noqa: E402  （复用 W6 的双引擎）

OLLAMA = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# ---------------------------------------------------------------- 分块


def split_chunks(text: str, size: int = 320, overlap: int = 60) -> List[str]:
    """按空行切段，太长的段再按句号切；相邻块留一点重叠，避免答案被切断。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    for para in paragraphs:
        if len(para) <= size:
            chunks.append(para)
            continue
        sentences = [s for s in re.split(r"(?<=[。！？])", para) if s.strip()]
        buf = ""
        for sentence in sentences:
            if len(buf) + len(sentence) <= size:
                buf += sentence
            else:
                if buf:
                    chunks.append(buf)
                buf = sentence
        if buf:
            chunks.append(buf)
    # 太短的块（比如只有一行标题）单独检索没意义，并进下一块
    merged_short: List[str] = []
    carry = ""
    for chunk in chunks:
        if len(chunk) < 120:
            carry += chunk + " "
            continue
        merged_short.append((carry + chunk).strip())
        carry = ""
    if carry:
        merged_short.append(carry.strip())
    chunks = merged_short

    # 给相邻块加一点重叠上下文
    if overlap > 0 and len(chunks) > 1:
        merged = []
        for i, chunk in enumerate(chunks):
            prefix = chunks[i - 1][-overlap:] if i else ""
            merged.append((prefix + chunk).strip())
        chunks = merged
    return chunks


# ---------------------------------------------------------------- 向量化


def _tokenize(text: str) -> List[str]:
    """中文按字符 bigram，英文数字按整词；够小语料用，不需要分词库。"""
    tokens: List[str] = []
    for seg in re.findall(r"[\u4e00-\u9fa5]+|[A-Za-z0-9]+", text):
        if re.fullmatch(r"[A-Za-z0-9]+", seg):
            tokens.append(seg.lower())
        elif len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


class TfidfIndex:
    """TF-IDF 向量 + 余弦相似度。断网也能建库。"""

    name = "tfidf"

    def __init__(self, docs: List[str]) -> None:
        self.docs = docs
        self.tokens = [_tokenize(d) for d in docs]
        df = Counter(token for doc in self.tokens for token in set(doc))
        n = max(1, len(docs))
        self.idf = {token: math.log((n + 1) / (count + 1)) + 1 for token, count in df.items()}
        self.vectors = [self._vectorize(tokens) for tokens in self.tokens]

    def _vectorize(self, tokens: List[str]) -> Dict[str, float]:
        counts = Counter(tokens)
        vec = {t: c * self.idf.get(t, math.log(len(self.docs) + 2)) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, question: str, k: int = 3) -> List[Tuple[float, int, str]]:
        q = self._vectorize(_tokenize(question))
        scored = []
        for i, vec in enumerate(self.vectors):
            score = sum(q.get(t, 0.0) * v for t, v in vec.items())
            scored.append((score, i, self.docs[i]))
        scored.sort(reverse=True, key=lambda item: item[0])
        return scored[:k]


class OllamaEmbedIndex:
    """nomic-embed-text 的神经向量；本机没这个模型时会被跳过。"""

    name = "ollama:" + EMBED_MODEL

    def __init__(self, docs: List[str]) -> None:
        self.docs = docs
        self.vectors = [self._embed(d) for d in docs]

    @staticmethod
    def _embed(text: str) -> List[float]:
        payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode("utf-8")
        request = urllib.request.Request(
            f"{OLLAMA}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))["embedding"]

    def search(self, question: str, k: int = 3) -> List[Tuple[float, int, str]]:
        q = self._embed(question)
        qn = math.sqrt(sum(v * v for v in q)) or 1.0
        scored = []
        for i, vec in enumerate(self.vectors):
            vn = math.sqrt(sum(v * v for v in vec)) or 1.0
            score = sum(a * b for a, b in zip(q, vec)) / (qn * vn)
            scored.append((score, i, self.docs[i]))
        scored.sort(reverse=True, key=lambda item: item[0])
        return scored[:k]


def _embed_backend_available() -> bool:
    try:
        OllamaEmbedIndex._embed("测试")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 建库 / 检索

_index: Optional[Any] = None


def get_retriever(rebuild: bool = False) -> Any:
    global _index
    if _index is not None and not rebuild:
        return _index
    text = CORPUS.read_text(encoding="utf-8")
    chunks = split_chunks(text)
    if _embed_backend_available():
        _index = OllamaEmbedIndex(chunks)
    else:
        _index = TfidfIndex(chunks)
    print(f"[rag] 后端={_index.name}，分块={len(chunks)}", file=sys.stderr)
    return _index


def retrieve(question: str, k: int = 3) -> List[Tuple[float, int, str]]:
    return get_retriever().search(question, k)


def build_prompt(question: str, hits: List[Tuple[float, int, str]]) -> str:
    context = "\n\n".join(f"[{i + 1}] {text}" for i, (_, _, text) in enumerate(hits))
    return (
        "你只能依据下面提供的资料回答，不要用资料以外的知识。\n"
        "如果资料里没有答案，就直接说“资料里没有”。\n"
        "回答后用括号标出你依据的片段编号，例如（依据 [2]）。\n\n"
        f"资料：\n{context}\n\n"
        f"问题：{question}\n"
        "回答："
    )


def ask_raw(question: str, prefer: str = "api") -> str:
    """裸答：不给资料，看模型自己会编什么。"""
    return LLM(prefer=prefer, verbose=False).ask(question).text


def rag_qa(question: str, prefer: str = "api", k: int = 3) -> Tuple[str, List[Tuple[float, int, str]]]:
    hits = retrieve(question, k)
    answer = LLM(prefer=prefer, verbose=False).ask(build_prompt(question, hits)).text
    return answer, hits


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="W7 RAG 最小实现")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="建库并打印分块数")
    p_search = sub.add_parser("search", help="只检索")
    p_search.add_argument("question")
    p_search.add_argument("-k", type=int, default=3)
    p_ask = sub.add_parser("ask", help="回答（默认带资料）")
    p_ask.add_argument("question")
    p_ask.add_argument("--prefer", choices=("local", "api"), default="api")
    p_ask.add_argument("-k", type=int, default=3)
    p_ask.add_argument("--raw", action="store_true", help="裸答，不检索")
    args = parser.parse_args(argv)

    if args.cmd == "build":
        index = get_retriever(rebuild=True)
        for i, doc in enumerate(index.docs):
            print(f"[{i}] {doc[:60]}…")
        return 0

    if args.cmd == "search":
        for score, i, text in retrieve(args.question, args.k):
            print(f"{score:.3f}  [{i}]  {text[:80]}…")
        return 0

    try:
        if args.raw:
            print(ask_raw(args.question, args.prefer))
            return 0
        answer, hits = rag_qa(args.question, args.prefer, args.k)
    except AllEnginesFailed as exc:
        print(f"两个引擎都没能回答：{exc}", file=sys.stderr)
        return 1

    print(answer)
    print("\n--- 检索到的片段 ---", file=sys.stderr)
    for score, i, text in hits:
        print(f"{score:.3f}  [{i}]  {text[:60]}…", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
