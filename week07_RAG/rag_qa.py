#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W7 · rag_qa.py —— RAG 四步：加载 → 分块 → 向量化 → 检索＋生成。

    ① 加载    TextLoader 读 week07_RAG/data.txt（不依赖当前工作目录）
    ② 分块    RecursiveCharacterTextSplitter，500 字 / 重叠 50
    ③ 向量化  nomic-embed-text 本地嵌入（ollama pull nomic-embed-text）
    ④ 检索    Chroma 找 top-k，拼进提示词
    ⑤ 生成    复用第 6 周的 llm.ask()（from llm import LLM），不另写一套调模型

作业 1 的进阶选的是「方案 A：给每段记录来源，让答案附出处」——
每块都带 `data.txt#序号`，提示词要求答案末尾标（依据 [n]）。

用法：

    python rag_qa.py build                 # 建库（首次；换文本会自动 rebuild）
    python rag_qa.py build --rebuild       # 强制重建
    python rag_qa.py search "本课几个把字句"
    python rag_qa.py ask "本课几个把字句" --prefer api
    python rag_qa.py ask "本课几个把字句" --raw      # 裸答，做幻觉对照

依赖见 requirements.txt；没装 langchain/chroma 时会退到内置的纯 Python 实现，
接口不变（老师说的“四步”仍然齐全），只是向量换成内置哈希向量。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import zlib
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import weekpath  # noqa: E402  数据路径 + .env + 跨周 import

weekpath.load_env()

from llm import LLM  # noqa: E402  week06 的统一入口（weekpath 负责找得到）

CORPUS = weekpath.data_path("data.txt")
PERSIST = weekpath.root_path("chroma_db")

try:  # 有依赖就走老师骨架的那一套
    from langchain_chroma import Chroma
    from langchain_community.document_loaders import TextLoader
    from langchain_core.embeddings import Embeddings
    from langchain_ollama import OllamaEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    HAS_LANGCHAIN = True
except ImportError:  # 机房没装依赖时的兜底，接口保持一致
    HAS_LANGCHAIN = False


# ---------------------------------------------------------------- 兜底向量

class HashEmbeddings:
    """字符 bigram 哈希到固定维度，纯 Python、断网可用（仅在缺依赖时启用）。"""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _vec(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for seg in re.findall(r"[\u4e00-\u9fa5]+|[A-Za-z0-9]+", text):
            grams = [seg[i : i + 2] for i in range(len(seg) - 1)] if len(seg) > 1 else [seg]
            for gram in grams:
                # 用 crc32 而不是 hash()：Python 的 hash 每次进程都变，会把持久化的库读坏
                vec[zlib.crc32(gram.encode("utf-8")) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._vec(text)


class OllamaHTTPEmbeddings:
    """没装 langchain 时直接用 Ollama 的 /api/embeddings 调 nomic-embed-text。

    比 HashEmbeddings 准得多，也不用为了一次嵌入装一整套 langchain。
    """

    def __init__(self, model: str = "nomic-embed-text") -> None:
        self.model = model
        self.url = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/") + "/api/embeddings"

    def _embed(self, text: str) -> List[float]:
        import urllib.request

        payload = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))["embedding"]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)


def _make_embeddings() -> Any:
    """优先本地 nomic-embed-text；没拉下来/没装依赖时逐级降级。"""
    if HAS_LANGCHAIN:
        try:
            emb = OllamaEmbeddings(model="nomic-embed-text")
            emb.embed_query("测试")  # 真调一次，避免建库到一半才报错
            print("[rag] 嵌入后端：nomic-embed-text（本地，768 维）", file=sys.stderr)
            return emb
        except Exception as exc:  # noqa: BLE001
            print(
                f"[rag] OllamaEmbeddings 不可用（{exc.__class__.__name__}），改试 HTTP 直连",
                file=sys.stderr,
            )

    try:
        emb = OllamaHTTPEmbeddings("nomic-embed-text")
        emb.embed_query("测试")
        print("[rag] 嵌入后端：nomic-embed-text（HTTP 直连，768 维）", file=sys.stderr)
        return emb
    except Exception as exc:  # noqa: BLE001
        print(
            f"[rag] nomic-embed-text 也不可用（{exc.__class__.__name__}），"
            "退回内置哈希向量；`ollama pull nomic-embed-text` 后 --rebuild 可切回",
            file=sys.stderr,
        )
        return HashEmbeddings()


# ---------------------------------------------------------------- 纯 Python 兜底库

class _Doc:
    def __init__(self, page_content: str, metadata: Dict[str, Any]) -> None:
        self.page_content = page_content
        self.metadata = metadata


def _bigrams(text: str) -> set:
    """中文按字符 bigram，英文数字按整词。检索和重排都用它。"""
    grams = set()
    for seg in re.findall(r"[\u4e00-\u9fa5]+|[A-Za-z0-9]+", text):
        if len(seg) > 1:
            grams.update(seg[i : i + 2] for i in range(len(seg) - 1))
        else:
            grams.add(seg)
    return grams


def _lexical_rerank(question: str, docs: List["_Doc"], k: int) -> List["_Doc"]:
    """关键词重排：nomic 是英文语料训的，中文短块单靠向量常把答案块排到后面。

    做法是“召回 + 重排”：先用向量召回一批候选，再用字符 bigram 的 IDF 权重
    （相当于轻量 BM25）重排，取前 k。问“几个词”时词汇块就能顶上来。
    """
    q_grams = _bigrams(question)
    doc_grams = [_bigrams(doc.page_content) for doc in docs]
    df: Dict[str, int] = {}
    for grams in doc_grams:
        for gram in grams:
            df[gram] = df.get(gram, 0) + 1
    total = max(1, len(docs))
    idf = {gram: math.log((total + 1) / (count + 1)) + 1 for gram, count in df.items()}

    scored = []
    for doc, grams in zip(docs, doc_grams):
        denom = math.sqrt((len(q_grams) or 1) * (len(grams) or 1))
        score = sum(idf.get(gram, 1.0) for gram in q_grams & grams) / denom
        scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored[:k]]


class SimpleVectorStore:
    """没有 Chroma 时的最小向量库：内存里存向量，余弦检索 + 关键词重排。"""

    def __init__(self, docs: List[_Doc], emb: HashEmbeddings) -> None:
        self.docs = docs
        self.emb = emb
        self.vectors = emb.embed_documents([d.page_content for d in docs])

    def similarity_search(self, question: str, k: int = 3) -> List[_Doc]:
        q = self.emb.embed_query(question)
        scored = [(sum(a * b for a, b in zip(q, vec)), i) for i, vec in enumerate(self.vectors)]
        scored.sort(reverse=True)
        return [self.docs[i] for _, i in scored[:k]]


# ---------------------------------------------------------------- 建库

def _corpus_fingerprint(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def _split_fallback(text: str, size: int = 500, overlap: int = 50) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    for para in paras:
        if len(para) <= size:
            chunks.append(para)
            continue
        for i in range(0, len(para), size - overlap):
            chunks.append(para[i : i + size])
    return chunks


def get_retriever(k: int = 3, rebuild: bool = False) -> Any:
    """建库或复用已有库，返回能 invoke/search 的检索器。"""
    emb = _make_embeddings()

    if HAS_LANGCHAIN:
        marker = os.path.join(PERSIST, ".corpus_sha")
        stamp = f"{_corpus_fingerprint(CORPUS)}|{type(emb).__name__}"
        stale = True
        if not rebuild and os.path.isdir(PERSIST) and os.listdir(PERSIST):
            try:
                stale = open(marker, encoding="utf-8").read().strip() != stamp
            except OSError:
                stale = True
        if stale:
            docs = TextLoader(CORPUS, encoding="utf-8").load()
            splits = RecursiveCharacterTextSplitter(
                chunk_size=500, chunk_overlap=50
            ).split_documents(docs)
            for i, split in enumerate(splits):
                split.metadata["source"] = f"data.txt#{i + 1}"  # 作业 1 方案 A：记来源
            vs = Chroma.from_documents(splits, emb, persist_directory=PERSIST)
            os.makedirs(PERSIST, exist_ok=True)
            open(marker, "w", encoding="utf-8").write(stamp)
            print(f"[rag] 重建完成：{len(splits)} 块 → {PERSIST}", file=sys.stderr)
        else:
            vs = Chroma(persist_directory=PERSIST, embedding_function=emb)
            print("[rag] 复用已有库（换文本请 --rebuild）", file=sys.stderr)
        return vs

    text = open(CORPUS, encoding="utf-8").read()
    chunks = _split_fallback(text)
    docs = [_Doc(chunk, {"source": f"data.txt#{i + 1}"}) for i, chunk in enumerate(chunks)]
    print(f"[rag] 兜底建库：{len(docs)} 块", file=sys.stderr)
    return SimpleVectorStore(docs, emb)


# ---------------------------------------------------------------- 检索 + 生成

def retrieve(question: str, k: int = 3) -> List[_Doc]:
    """召回 + 重排：向量先取一批候选，关键词 IDF 重排后返回 top-k。"""
    store = get_retriever()
    candidates = store.similarity_search(question, k=max(10, k * 4))
    return _lexical_rerank(question, candidates, k)


def build_prompt(question: str, docs: List[_Doc]) -> str:
    """提示词里写死「资料中没有就如实说」，把幻觉压到最低。"""
    blocks = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "资料")
        blocks.append(f"[{i}]（来源 {source}）{doc.page_content}")
    context = "\n\n".join(blocks)
    return (
        "根据以下资料回答问题。资料中没有的内容就如实说「资料中未提及」，不要用资料以外的知识补。\n\n"
        f"资料：\n{context}\n\n"
        f"问题：{question}\n\n"
        "要求：先给答案，末尾用（依据 [n]）标出你用到的是第几段资料。"
    )


def rag_qa(question: str, prefer: str = "local", k: int = 3) -> Any:
    """带资料回答：检索 → 拼提示词 → 交给 W6 的 llm.ask()。"""
    docs = retrieve(question, k)
    answer = LLM().ask(build_prompt(question, docs), prefer=prefer)
    answer.sources = docs  # 调用方要出处时直接取
    return answer


def ask_raw(question: str, prefer: str = "api") -> Any:
    """裸答：不检索、不给资料，用来做幻觉对照。"""
    return LLM().ask(question, prefer=prefer)


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="W7 RAG：加载→分块→向量化→检索+生成")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build", help="建库")
    p_build.add_argument("--rebuild", action="store_true")
    p_search = sub.add_parser("search", help="只检索")
    p_search.add_argument("question")
    p_search.add_argument("-k", type=int, default=3)
    p_ask = sub.add_parser("ask", help="回答")
    p_ask.add_argument("question")
    p_ask.add_argument("--prefer", choices=("local", "api"), default="local")
    p_ask.add_argument("-k", type=int, default=3)
    p_ask.add_argument("--raw", action="store_true", help="裸答，不检索")
    args = parser.parse_args(argv)

    if args.cmd == "build":
        store = get_retriever(rebuild=args.rebuild)
        total = store._collection.count() if hasattr(store, "_collection") else len(store.docs)
        print(f"库就绪：{total} 块")
        for doc in store.similarity_search("把字句", k=3):
            print(f"{doc.metadata.get('source', '?')}  {doc.page_content[:60]}…")
        return 0

    if args.cmd == "search":
        for doc in retrieve(args.question, args.k):
            print(f"{doc.metadata.get('source', '?')}  {doc.page_content[:80]}…")
        return 0

    if args.raw:
        print(ask_raw(args.question, args.prefer).text)
        return 0

    answer = rag_qa(args.question, args.prefer, args.k)
    print(answer.text)
    print("\n--- 检索到的片段 ---", file=sys.stderr)
    for i, doc in enumerate(answer.sources, start=1):
        print(f"[{i}] {doc.metadata.get('source', '?')}  {doc.page_content[:50]}…", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
