# 第 8 周 · 5 行映射表

> 第三列全部来自我自己的 `week07_RAG/rag_qa.py` 与 `week08_助手v1.0/assistant_v1.py`，不是抄讲义。

| # | 官方流水线 | llm-universe 对应章节 | 我自己的代码（真实函数/类名） |
|---|---|---|---|
| 1 | Load + Split | C3「数据处理」 | `TextLoader(weekpath.data_path("data.txt"), encoding="utf-8")` + `RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)`，语料是 `week07_RAG/data.txt` |
| 2 | Embed + Store | C3「词向量 / Embedding / 向量库」 | `OllamaEmbeddings(model="nomic-embed-text")` → `Chroma.from_documents(splits, emb, persist_directory=PERSIST)`，持久化到根目录 `chroma_db/` |
| 3 | Retrieve | C4「检索问答链」的检索部分 | `retrieve(question, k=3)`：先 `Chroma.similarity_search(question, k=10)` 召回，再用 `_lexical_rerank()` 按中文 bigram IDF 重排取 top-3；`use_rag=True` 时先 retrieve 再 build_prompt |
| 4 | Prompt + Generate | C4「接入 LLM」 | `build_prompt(question, docs)` 拼三段：`SYSTEM_HINT` + 「[1]…[3]（来源 data.txt#n）」资料块 + 「资料中没有就如实说、末尾标（依据 [n]）」；最后调 `LLM().ask(prompt, prefer=..., max_tokens=400)` |
| 5 | Deploy + Evaluate | C4「Streamlit 部署」/ C5「系统评估与优化」 | 评估：W7 的 `week07_RAG/hallucination_log.md`（5 组裸答 vs RAG）；部署：目前是 CLI（`python assistant_v1.py`），W15 计划用 Streamlit 包一层并随 Release 发布 |

## 一句话

官方那套「load → split → embed → store → retrieve → generate」我一步没少，换的是组件（云端 embeddings → 本地 nomic）和语料（英文示例 → HSK 课文）；多出来的一步是中文关键词重排，因为 nomic 对中文短块召回不稳。
