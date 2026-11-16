# 第 8 周 · 读文档记录（三句话）

1. **2-Step RAG 是什么**：检索永远发生在生成之前——先把资料切块、向量化、存进向量库，再把问题向量化去检索 top-k，把检索结果拼进提示词交给模型生成答案；流程固定、LLM 只调用一次，适合 FAQ 和文档问答。
2. **llm-universe 的 C3 做了什么**：讲「词向量、Embedding、数据处理、向量库」四件事，也就是把一堆原始文档变成可以按语义检索的向量并入库。
3. **llm-universe 的 C4 做了什么**：讲「接入 LLM、检索问答链、Streamlit 部署」三件事，也就是把检索到的内容和模型接成一条问答链，再包一个能点的网页界面。

参考来源与许可证说明：

- LangChain 官方 Retrieval / 2-Step RAG 文档：<https://docs.langchain.com/oss/python/langchain/rag>
- Datawhale llm-universe 在线阅读：<https://datawhalechina.github.io/llm-universe/>（C3、C4）
- 该仓库**没有 LICENSE 文件**，按默认规则「保留所有权利」——我只读文档、学思路，**没有复制它的代码**；本文只是自己的一句话概括，不是原文搬运。
