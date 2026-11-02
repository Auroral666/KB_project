# 混合检索首版运行说明

基线：`7f3e4c6 第一版`。本次保留 SQLite、Milvus 集合、上传目录和既有会话；验证使用独立空间。

## 启动

1. 安装 `requirements.txt`（相对基线仅新增 `neo4j==5.26.0`）。现有 Python 环境可仅安装该驱动。
2. `.env` 增加 `neo4j_password`，其余默认值见 `.env.example`。本次实施已在本机生成密码，不提交到 Git。
3. 启动 Docker Desktop，保持现有 Milvus 可用；双击 `启动_停止项目/启动项目.cmd`。
4. 网页：`http://127.0.0.1:8010`；Neo4j Browser：`http://127.0.0.1:7474`，用户名 `neo4j`，密码读取本机 `.env`。

单独启动 Neo4j：在项目根目录执行 `python -B -X utf8 -m app.neo4j_cli`，或 `docker compose -p kb-project -f compose.neo4j.yml up -d`。镜像固定为 `neo4j:5.26.0-community`，数据在 Compose 命名卷。停止网页不会停止数据库；停止专属图谱容器可执行对应 Compose `stop`，不要加 `-v` 删除数据。

若使用现有 Langfuse 观测入口，先启动 Neo4j，再沿用 `langfuse/启动观测.cmd`。普通入口与观测入口共用8010端口，二者择一。本次最终保留观测入口运行。

关闭图谱可配置 `neo4j_enabled=false`，继续使用语义分块和向量检索；此时不抽取或写入图谱。`history_turns=4` 控制最近轮数，0 禁用窗口。`semantic_threshold=0.55` 控制相邻句余弦相似度的合并边界，每片最多512字符，保持页码。

## 接口与流程

|接口|说明|
|---|---|
|`POST /api/index-jobs`|multipart `file`；202返回`task_id`和`job`|
|`GET /api/index-jobs`|最近100项任务|
|`GET /api/index-jobs/{task_id}`|状态、阶段、失败原因、文档编号|
|`POST /rag/create/`|保留原同步建库接口|
|`POST /rag/chat/`|原问答接口，新增`rewritten_question`和`graph`|
|`POST /rag/chat/stream/`|原SSE接口，新增`graph`事件|
|`GET /api/status`|新增`graph.enabled/connected`连接状态|

任务阶段：`waiting → semantic_chunking → extracting_relations → writing_vectors → writing_graph → complete`；状态为`queued/running/succeeded/failed`。上传内容先保存，随后单线程建库。重启恢复排队/运行任务；运行任务重建时先清除其文档编号下的部分写入。模型调用在全局写锁外；仅索引写入和删除串行，问答检索不持有该写锁。嵌入计算另有模型锁。

两种索引写完后才提交文档清单；检索根据清单过滤部分写入或已删文档。失败补偿尝试移除两种索引，清理成功后移除临时原文件；清理失败会记日志并保留文件便于修复。Milvus与Neo4j不具备跨库原子事务，服务同时故障时仍需按任务编号排查残留。仅支持当前单进程服务入口；不要使用多个Uvicorn工作进程共享任务队列。

Neo4j使用参数化查询，实体按命名空间及规范化名称合并；关系按文档、片段和三元组生成稳定编号，并携带原文、逐字依据和页码。抽取结果必须能在块中逐字验证主体、客体和依据；不合格条目会被跳过，其余关系继续入库。没有有效关系的文档仍完成向量建库，不写入图谱。模型服务不可用或输出整体格式错误仍报告任务失败。关系语义的真实性仍依赖模型和人工核对；同名实体会合并，首版不做实体消歧。

检索并行发起向量Top5与实体匹配的两跳图谱查询；必要时使用向量命中文档作为图谱入口。按文档与片段去重，采用倒数排名融合，最多12条来源。单路故障时用可用证据并显示降级说明；双路均故障时返回错误。图谱展示召回证据中涉及的关系，代表本次提供给模型的上下文；不声称每条边都被回答实际采用。来源点击仍打开完整原文件。

旧文档不会自动抽取关系；重新上传可生成图谱。首版不提供取消任务、自动重试失败任务、批量补建旧文档或分布式队列。

## 验证

离线回归：`python -B -X utf8 -m unittest discover -s tests -p 'test_*.py' -v`。

DOM回归：`node tests/test_markdown.cjs`、`node tests/test_citations.cjs`、`node tests/test_original_document.cjs`、`node tests/test_knowledge_graph.cjs`。测试依赖按 `tests/README.md` 安装到 `temp/dev-tools`。

真实对照：`python -B -X utf8 tests/evaluate_hybrid.py`。需要Neo4j、Milvus、嵌入模型和模型接口；会产生模型调用费用。使用 `tests/hybrid_cases.json` 的12份小文档及12条固定问题，对比原独立向量流程与新混合流程，记录完整回答、独立问题、来源、引用覆盖及耗时。SQLite和文件在`temp/sprint/evaluation-*`，向量集合和图谱命名空间使用随机`kb_eval_*`，结束清理隔离索引。自动关键词分数不等于人工评审准确率，不作为统计显著性结论。

实际验收结果见 [冲刺验证记录](sprint-validation.md)。

## 文档选择删除与任务界面

知识库页面可勾选文档并点击“删除所选文档”，也可使用每行的“删除”按钮。新增 `POST /api/documents/delete`，JSON 为 `{"doc_ids":["32位文档编号"]}`，最多100个；返回 `deleted` 与 `failed`，逐项报告部分失败。删除同时移除原文件、向量片段和图谱关系，保留历史会话。原有 `DELETE /api/documents/{doc_id}` 继续可用。

“查看知识图谱”在新标签打开 `http://127.0.0.1:7474/browser/`。登录后可运行 `MATCH p=(a:KBEntity {namespace: 'kb_project_knowledge'})-[r:KB_RELATION]->(b) RETURN p LIMIT 100` 查看默认项目空间（自定义空间请替换namespace）。

任务区域显示文件名、状态、时间、当前阶段和独立失败原因；历史失败记录保留，旧失败文件需重新上传，修复不会将旧失败任务伪装为成功。
