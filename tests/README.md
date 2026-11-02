# 回归验证

从项目根目录执行。测试使用临时数据库和文件、模拟外部模型与向量服务，不修改现有知识库及会话。

## Python

继续使用现有环境，无需重新安装。

```powershell
& 'F:\anaconda\anaconda3\envs\rag-env\python.exe' -B -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
```

新环境可安装 `tests/requirements.txt`。测试覆盖页面、文档上传及失败补偿、大小和路径限制、完整原文、PDF 模块类型、普通与流式问答、会话持久化、统计、检索缓存失效和旧数据库迁移。

## 页面交互逻辑

DOM 测试不需要启动服务。Node 依赖统一放在 `temp/dev-tools/`，项目整理时已保留，可直接执行：

```powershell
node tests/test_markdown.cjs
node tests/test_citations.cjs
node tests/test_original_document.cjs
node tests/test_knowledge_graph.cjs
```

如果以后清理了测试依赖，复制依赖清单后重新安装：

```powershell
New-Item -ItemType Directory -Force temp/dev-tools | Out-Null
Copy-Item -LiteralPath tests/package.json -Destination temp/dev-tools/package.json
npm install --prefix temp/dev-tools
```

Node 版本需满足 `jsdom` 的要求：20.19+、22.12+ 或 24+。覆盖 Markdown 渲染和脚本过滤、引用编号及多文件映射、完整原文保留、文字范围定位和缺失文件提示。PDF 的真实页面绘制还需在运行页面中验证。

使用 `-B` 避免产生分散的 Python 字节码缓存。测试输出可以重定向到 `temp/`。

混合检索回归新增 `test_hybrid.py`，仍模拟外部服务并使用隔离数据库。真实服务的12条对照须单独运行 `python -B -X utf8 tests/evaluate_hybrid.py`，会调用模型接口并使用隔离 Milvus 集合和 Neo4j 命名空间；固定资料见 `hybrid_cases.json`。方法与限制见 `docs/hybrid-rag.md`，已执行结果见 `docs/sprint-validation.md`。
