# 项目结构与维护约定

应用主线集中在 `app/`。根目录只保留启动入口、配置、依赖清单、说明与许可证；数据、测试和临时内容各自独立。

## 职责与依赖

```text
app/main.py                 组装应用、生命周期、通用中间件
  └─ api/                   请求校验、路由、HTTP 响应和流式传输格式
       ├─ services/         文档管理、检索、回答生成与完成后保存
       │    └─ repositories/ SQLite 数据访问
       └─ repositories/     只读文档列表、会话与统计查询
```

- `api/chat.py`：问答参数校验、普通响应及 SSE 编码；不直接执行检索或写 SQL。
- `api/documents.py`：上传、下载、原文、移除和清空接口，以及业务错误到 HTTP 状态的转换。
- `api/workspace.py`：页面、健康检查、服务状态、会话和统计读取。
- `services/chat.py`：串联检索、生成和存储；仅将完整回答写入历史。流式函数输出普通事件字典，可独立于 HTTP 调用。
- `services/documents.py`：上传文件及索引的生命周期、大小校验、失败补偿、完整原文读取。
- `services/document_parser.py`：PDF、DOCX、TXT、Markdown 的解析和分块。
- `services/rag.py`：向量库连接、检索缓存、模型复用、预热及生成。
- `services/knowledge_graph.py`：有依据的关系抽取、Neo4j 写入、两跳查询与局部图谱数据。
- `services/index_jobs.py`：持久化后台建库任务、单线程处理及重启恢复。
- `services/embeddings.py`：嵌入模型适配，保留上游署名。
- `repositories/workspace.py`：SQLite 连接、建表和兼容迁移、文档清单、会话、消息与统计 SQL。
- `web/templates/`、`web/static/`：页面、样式、交互和本地第三方组件。对外资源地址仍是 `/static/...`。
- `config.py`：统一定位项目根目录、配置、持久数据和页面资源，路径不依赖启动时的工作目录。
- `__main__.py`：前台启动入口；`cli.py`：后台服务的启动、归属校验、就绪检查和停止。

业务服务不导入 FastAPI，存储模块不依赖路由或业务服务。新增业务应在对应服务中实现，接口仅负责输入输出，避免将业务重新堆入 `main.py`。当前规模使用普通函数模块，不增加仅转发调用的接口层。

## 需要保留的数据

| 位置 | 用途 |
| --- | --- |
| `.env` | 本机配置与模型密钥，不提交版本管理 |
| `data/workspace.db` | 文档清单、会话、完整回答、引用和统计 |
| `data/workspace.db-wal`、`data/workspace.db-shm` | SQLite 运行时关联文件，不在运行期间手工移动 |
| `upload_files/` | 用户实际上传的原文件，按文档 ID 命名 |
| Milvus `kb_project_knowledge` | 本项目向量索引，仍使用现有独立服务 |
| Docker 卷 `kb-project_neo4j_data` | 通过项目 Compose 启动的图谱实体、关系及来源 |

SQLite 清单与任务、原文件、Milvus 和 Neo4j 索引是配套数据。移动程序文件无需重建索引；不要把原文件或数据库当作临时文件。

## 临时内容与历史归档

`temp/` 已加入忽略清单，不作为应用源代码的一部分。

| 子目录 | 内容 |
| --- | --- |
| `backup/` | 整理前的代码压缩包和一致性数据库备份 |
| `archive/` | 旧入口、旧目录、旧 README 和原始完整依赖清单 |
| `reports/` | 以往的导入记录、测速与验收报告 |
| `screenshots/` | 以往的页面验收截图 |
| `diagnostics/` | 以往的压测脚本、手工上传样本 |
| `cache/` | 旧 Python 缓存 |
| `dev-tools/` | DOM 测试所需的 Node 依赖，可按 `tests/README.md` 重建 |
| `logs/` | 整理前的日志和进程号 |
| `runtime/` | 当前服务日志与后台进程记录 |
| `restructure/` | 本次文件移动清单、数据指纹、检查脚本和验证结果 |

归档文件用于追溯，可能仍包含旧路径，不作为当前启动入口。服务停止后可清理不需要的临时内容；清空 `temp/` 会同时丢失备份、日志和测试依赖，运行期间请保留 `temp/runtime/service.json`，供停止入口核实进程归属。

## 兼容与验证

浏览器页面、静态资源 URL、旧同步上传、问答和原文接口沿用现有地址；页面上传改用新增后台任务接口。根目录 `main.py` 保留为兼容入口；启停脚本位于 `启动_停止项目/`，实际应用位于 `app/`。当前混合检索与任务约定见 [运行说明](hybrid-rag.md)。

整理后的验证包括原有 19 项后端回归测试、Markdown/引用/全文定位 DOM 测试、启停与重复启停、线上页面及 PDF 原文件检查。使用前后数据指纹验证数据库逻辑行和上传文件未因文件迁移发生变化。
