#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekpath —— 课程骨架里的路径辅助模块（最小实现）。

课程原版有 `weekpath` 这个模块，负责三件事；这里按同样接口补一份：

    weekpath.root_path("chroma_db")   项目根目录下的路径
    weekpath.data_path("data.txt")    week07_RAG/data.txt
    weekpath.load_env()               读项目根的 .env（不覆盖已有环境变量）

外加第四件事：把 `week06_双引擎/` 加进 sys.path，
这样 `from llm import LLM` 才能跨周 import（老师说的“靠 weekpath 跨周 import，
别手写相对路径”，就是这个意思）。

项目根 = 本文件所在目录：
    ai-portfolio/
    ├── weekpath.py          ← 本文件
    ├── week05_local_deploy/
    ├── week06_双引擎/llm.py
    └── week07_RAG/rag_qa.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def root_path(*parts: str) -> str:
    """项目根目录下的路径，例如 root_path("chroma_db")。"""
    return str(ROOT.joinpath(*parts))


def data_path(name: str = "data.txt") -> str:
    """week07_RAG/ 下的数据文件路径。"""
    return str(ROOT / "week07_RAG" / name)


def load_env(path: str | None = None) -> None:
    """读 .env（KEY=VALUE 一行一个），已存在的环境变量不覆盖。"""
    env_file = Path(path) if path else ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# 跨周 import：把 week06_双引擎 放进搜索路径，`from llm import LLM` 才找得到
_W6 = ROOT / "week06_双引擎"
if _W6.exists() and str(_W6) not in sys.path:
    sys.path.insert(0, str(_W6))
