# 知屿 · Knowledge Studio

面向个人资料的 RAG 知识工作台。上传文档后，通过自然语言提问，并直接定位回答所引用的完整原文。

## 运行

双击根目录的 **`启动项目.cmd`**。完成就绪检查后访问 <http://127.0.0.1:8010>。双击 **`停止项目.cmd`** 停止服务。

默认继续使用已有 Python 环境：

```text
F:\anaconda\anaconda3\envs\rag-env\python.exe
```

关闭启动窗口后，后台服务继续运行。重复启动会识别已有实例；停止入口只停止本目录管理的进程，不停止原项目或共享的 Milvus 服务。Milvus 仍需在本机运行，配置沿用当前 `.env`。

也可从 PowerShell 使用兼容入口：

```powershell
.\start.ps1
.\stop.ps1
# 指定其他 Python 环境：
.\start.ps1 -PythonPath '你的环境\python.exe'
```

双击入口可通过环境变量 `RAG_PYTHON` 指定 Python。自动化调用时设置 `KB_NO_PAUSE=1` 可免去结束时的按键等待。

前台调试入口如下；在项目根目录运行，按 Ctrl+C 停止该前台实例：

```powershell
& 'F:\anaconda\anaconda3\envs\rag-env\python.exe' -B -X utf8 -m app
# 原有入口仍可用：python -B main.py
```

健康检查：`GET /health`。启动成功表示网页服务已就绪；嵌入模型继续在后台预热，状态可通过 `GET /api/status` 查看。当前运行日志在 `temp/runtime/server.log`、`server-error.log`，进程归属记录在同目录的 `service.json`。

## 项目目录

```text
KB_project/
├─ app/                      应用主线
│  ├─ main.py                应用组装、生命周期、中间件
│  ├─ __main__.py            前台启动入口
│  ├─ cli.py                 后台启停与就绪检查
│  ├─ config.py              配置与统一路径
│  ├─ api/                   页面、问答、文档 HTTP 接口
│  ├─ services/              问答、文档管理、解析、检索与模型
│  ├─ repositories/          SQLite 数据访问
│  └─ web/
│     ├─ templates/          页面模板
│     └─ static/             样式、交互、图标与本地第三方组件
├─ data/                     持久数据库
├─ upload_files/             用户上传的原文件
├─ tests/                    正式回归测试与开发依赖清单
├─ docs/                     架构及维护说明
├─ temp/                     临时内容、历史归档、备份、日志与测试工具
├─ main.py                   兼容旧启动命令的薄入口
├─ 启动项目.cmd / 停止项目.cmd
├─ start.ps1 / stop.ps1      PowerShell 入口
├─ .env / .env.example       本机配置 / 配置示例
├─ requirements.txt          实际运行依赖
└─ LICENSE / NOTICE          许可证和上游署名
```

接口层负责输入输出，业务服务负责流程，存储模块负责 SQL，页面资源独立放置。详细职责、依赖方向和数据维护约定见 [架构说明](docs/architecture.md)。

## 功能

- **工作台**：文档、知识片段与问答概览，近期问答趋势、知识构建状态和最近文档。
- **智能问答**：流式回答，渲染 Markdown 标题、表格、列表及代码；问题在右、助手回答在左，自动保存完整对话。
- **引用与原文**：点击 `[1]`、`[2]` 或文件引用条，右侧以文档标签页展示完整原文；定位引用位置并黄色高亮，支持 PDF 翻页、缩放及下载。引用条显示文件名和片段，空间不足时省略。
- **知识库**：支持 PDF、DOCX、TXT、Markdown，单文件上限 20 MB；提供搜索、筛选、下载、移除和清空操作。
- **数据洞察**：7/30 天问答趋势、资料命中率、完整回答耗时、文件构成及最近问答依据。

所有指标来自本项目的真实记录。失败或未完成的回答不计入已完成问答；资料命中率不等于答案准确率。耗时包含检索与完整模型生成，首次请求还可能受模型预热影响。

每个问题独立检索，同一会话用于保存记录，之前的对话不会自动加入模型上下文。文档、会话和索引存储在本机；问题和命中的资料片段发送至 `.env` 配置的模型服务生成回答。

## 配置与数据

现有 `.env`、`data/workspace.db` 和 `upload_files/` 均沿用原位置，整理目录不要求重新上传资料或重建索引。当前向量集合仍是 `kb_project_knowledge`。

新环境从 `.env.example` 复制配置，填写模型地址、密钥、嵌入模型位置和 Milvus 连接信息；运行依赖在 `requirements.txt`，开发测试说明见 [tests/README.md](tests/README.md)。本次使用现有环境，没有更换 Python 或重新安装运行依赖。

SQLite 会话、文档清单、上传原件和 Milvus 索引需要配套备份。`.env` 含密钥，请勿提交版本管理。上传原文件与数据库是持久数据，不放入 `temp/`。

## 临时内容

此前散落的截图、测速结果、手工验收样本、旧日志、Python 缓存和 DOM 测试工具已统一归入 `temp/`。整理前的代码和数据库备份位于 `temp/backup/`，逐项移动清单位于 `temp/restructure/moves.json`。旧入口和旧依赖清单保存在 `temp/archive/`，供追溯使用。

新日志统一写入 `temp/runtime/`；DOM 测试工具统一放在 `temp/dev-tools/`。清理临时目录前请先停止服务，并按需保留备份。

## 组件与许可

Markdown、HTML 安全过滤和 PDF 原文预览使用本地的 Marked、DOMPurify、PDF.js，组件及许可证随 `app/web/static/vendor/` 一并保留。项目继续保留上游 Apache 2.0 的 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
