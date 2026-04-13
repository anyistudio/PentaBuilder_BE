# PentaBuilder Backend Implementation Design

## 1. 文档目标

这份文档回答“后端应该怎么实现”，重点不是概念，而是：

1. 代码目录怎么拆。
2. 每个模块负责什么。
3. 请求进入后端后，经过哪些步骤。
4. 离线 workflow 如何和在线 API 共用一套能力。
5. 第一阶段应该按什么顺序开发。

后端包管理与运行入口统一使用 `uv`。

它和另外两份文档的关系：

- [ARCHITECTURE_DESIGN.md](/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/docs/ARCHITECTURE_DESIGN.md)：讲整体架构与边界
- [DB_SCHEMA_DESIGN.md](/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/docs/DB_SCHEMA_DESIGN.md)：讲数据结构
- [API_CONTRACT.md](/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/docs/API_CONTRACT.md)：讲外部接口

## 2. 实现目标

v1 后端要完成以下闭环：

1. 读取当前 `data_version` 的游戏数据
2. 处理匿名和登录用户的 AI 请求
3. 支持评分、推荐、解释、对比、继续追问
4. 保存登录用户 session 和 run metadata
5. 支持强缓存与参考缓存
6. 维护 leaderboard
7. 提供 admin 手动触发的离线任务

## 3. 代码组织建议

建议以 `app/` 为主包：

```text
PentaBuilder_BE/
├── app/
│   ├── api/
│   │   ├── deps/
│   │   ├── routes/
│   │   ├── schemas/
│   │   └── sse/
│   ├── core/
│   │   ├── config.py
│   │   ├── constants.py
│   │   ├── enums.py
│   │   ├── logging.py
│   │   ├── security.py
│   │   └── errors.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   ├── models/
│   │   └── repositories/
│   ├── domain/
│   │   ├── match_context.py
│   │   ├── response_preferences.py
│   │   ├── cache_keys.py
│   │   ├── leaderboard.py
│   │   └── transcript.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── catalog_service.py
│   │   ├── data_version_service.py
│   │   ├── session_service.py
│   │   ├── ai_run_service.py
│   │   ├── cache_service.py
│   │   ├── leaderboard_service.py
│   │   ├── storage_service.py
│   │   └── benchmark_service.py
│   ├── ai/
│   │   ├── llm_base.py
│   │   ├── providers/
│   │   ├── prompts/
│   │   ├── tools/
│   │   ├── agents/
│   │   ├── orchestration/
│   │   └── grading/
│   ├── jobs/
│   │   ├── baselines.py
│   │   ├── calibrations.py
│   │   ├── benchmarks.py
│   │   └── maintenance.py
│   ├── cli/
│   │   └── main.py
│   └── main.py
├── migrations/
└── tests/
```

## 4. 模块职责

## 4.1 `api/`

职责：

- 定义 HTTP 路由
- 解析请求
- 做最外层参数校验
- 处理认证依赖
- 调用 service
- 统一返回 response envelope

不要在 `api/routes` 里做的事情：

- 拼 prompt
- 直接访问 object storage
- 直接操作 SQLAlchemy model

## 4.2 `core/`

职责：

- 配置管理
- 常量
- logging
- 安全校验
- 全局错误类型

建议在这里定义：

- 环境变量 schema
- `Game` / `RunType` / `Language` 常量
- request id 中间件
- 统一异常映射

## 4.3 `db/`

职责：

- SQLAlchemy model
- repository 层
- DB session 管理

推荐 repository 粒度：

- `users_repository.py`
- `sessions_repository.py`
- `ai_runs_repository.py`
- `cache_repository.py`
- `leaderboard_repository.py`
- `data_versions_repository.py`

repository 只负责：

- CRUD
- 查询拼装

不要在 repository 里做：

- 业务策略判断
- 缓存命中逻辑
- object storage 删除

## 4.4 `domain/`

职责：

- 纯领域对象
- 规范化逻辑
- canonical key 生成
- transcript event shape

这里应该保持尽可能纯净，可直接单元测试。

建议放入：

- `MatchContext`
- `ResponsePreferences`
- `RunPayload` 各种类型
- `canonicalize_enemy_comp()`
- `build_semantic_context_hash()`
- `build_response_variant_hash()`

## 4.5 `services/`

职责：

- 真正的业务编排层
- 连接 DB、AI、object storage、catalog

这是后端最重要的一层。

### 建议服务划分

#### `auth_service`

- 验证 Clerk token
- 查找或创建用户
- 签发后端 access token
- 提供 admin 固定账号密码鉴权能力

#### `catalog_service`

- 暴露 champions/items/runes 目录查询
- 处理语言展示与黑话映射
- 保证 slug 使用统一的 `lol-` / `wr-` canonical 前缀

#### `data_version_service`

- 获取当前 active version
- 激活新版本
- 触发版本切换后的缓存清理

#### `session_service`

- 创建 session
- 读取 session
- 删除 session
- claim 匿名 session buffer
- 管理 transcript object
- v1 匿名用户默认不落库，只有登录后 claim / save 才进入持久化层

#### `ai_run_service`

- 统一处理所有 AI run 请求
- 做上下文规范化
- 判断缓存策略
- 调用 AI orchestration
- 落库 run metadata
- 写 artifact
- 更新 session transcript

#### `cache_service`

- 强缓存命中
- 参考缓存查找
- 缓存写入
- 缓存失效/清理

#### `leaderboard_service`

- 从评分 run 更新 leaderboard
- 删除 session/user 后重算受影响 entry

#### `storage_service`

- 上传/下载/删除 object storage 对象
- 统一生成 object key

#### `benchmark_service`

- 加载 benchmark dataset
- 调度模型批测
- 聚合 accuracy / latency / cost

## 4.6 `ai/`

职责：

- LLM provider 抽象
- prompt 组装
- tool interface
- agent 执行逻辑
- benchmark grading

复杂的多步 agentic workflow 统一使用 `LangGraph` 实现；不要引入额外的自由形态 agent framework。

推荐拆法：

### `providers/`

- `openai_client.py`
- `gemini_client.py`

### `tools/`

- `catalog_tools.py`
- `baseline_tools.py`
- `calibration_tools.py`

### `agents/`

- `evaluate_build_agent.py`
- `recommend_build_agent.py`
- `explain_slot_agent.py`
- `compare_builds_agent.py`
- `chat_followup_agent.py`

### `orchestration/`

- `run_dispatcher.py`
- `prompt_builder.py`
- `stream_adapter.py`

### `graphs/`

- `online_run_graph.py`
- `state.py`
- `nodes.py`
- `validators.py`
- `translators.py`

## 4.7 `jobs/`

职责：

- 跑离线 workflow
- 共用 service 和 ai layer

不要让 jobs 复制一套独立逻辑。它们应该复用在线链路。

## 5. 应用启动流程

后端启动时建议按以下顺序初始化：

1. 加载配置
2. 初始化 logging
3. 初始化 DB engine 与 sessionmaker
4. 初始化 object storage client
5. 初始化 provider client registry
6. 加载当前 active `data_version`
7. 读取对应的 champions/items/runes JSON 到内存索引
8. 构建 lookup 索引和 localization 索引
9. 挂载 FastAPI routes

关键点：

- 游戏数据应在启动时加载一次
- 版本切换时通过 admin job 触发 reload
- API 请求不应在热路径反复读取 S3 原始 JSON

## 6. 游戏数据加载实现

## 6.1 `GameDataRegistry`

建议做一个进程级只读 registry：

```python
class GameDataRegistry:
    active_version: str
    catalogs: dict[str, GameCatalog]
```

其中 `GameCatalog` 至少包括：

- champions by slug
- items by slug
- runes by slug
- lookup index by normalized name
- localization map

补充约束：

- slug 必须统一保存为 canonical 格式：
  - `lol-...`
  - `wr-...`
- `localization map` 应来自单独生成并可人工修订的资产，而不是运行时临时翻译
- 这份本地化资产应支持从本地目录或 object storage 读取，然后在进程内缓存

## 6.2 Reload 策略

版本切换时：

1. admin API 触发 activate version job
2. job 校验 manifest
3. 更新 `data_versions.is_active`
4. 重新加载 registry
5. 清理缓存

建议加一层读写锁或原子替换，避免 reload 中途请求读到半成品。

## 7. 在线请求处理链路

## 7.1 Catalog 请求

流程：

1. route 解析 path/query
2. service 校验 game 与 version
3. 从 `GameDataRegistry` 读取
4. 应用语言与术语风格 formatter
5. 返回轻量 DTO

## 7.2 AI Run 请求

统一流程建议如下：

1. route 解析请求并构造 domain object
2. auth dependency 解析当前用户，可为空
3. `ai_run_service` 校验：
   - run_type
   - session ownership
   - slot index
   - environment tags
   - slug 前缀与 `game` 是否一致
4. 规范化上下文：
   - enemy heroes 排序
   - environment tags 排序
   - 生成 canonical key
5. 判断缓存策略：
   - 无 free_text -> 尝试强缓存
   - 有 free_text -> 只查参考缓存
6. 若强缓存命中：
   - 直接返回缓存结果
   - 仍写 `ai_runs`
7. 若未命中：
   - 构建 prompt
   - 注入 localization bundle
   - 附加 calibration summary
   - 注册 tools
   - 调用目标 agent
8. 收到结果后：
   - 写 artifact object
   - 写 `ai_runs`
   - 如满足条件，写 `cached_context_results`
   - 如是评分 run，更新 leaderboard
   - 如绑定 session，更新 transcript

## 7.3 Session 删除请求

流程：

1. 校验 session owner
2. 读出 transcript key 与关联 run ids
3. 删除 run artifact
4. 删除 transcript object
5. 删除 `ai_runs`
6. 删除 `sessions`
7. 重算 leaderboard

因为你要求同步删除 object，这个流程必须写在 service 层，不能只靠 DB cascade。

## 8. Prompt 构建策略

你已经决定先不做正式 prompt version 管理，因此实现上建议采取“固定模板 + 小函数拼接”。

推荐目录：

```text
ai/prompts/
├── shared/
│   ├── system_principles.md
│   ├── output_contracts.md
│   └── calibration_attachment.md
├── evaluate_build.md
├── recommend_build.md
├── explain_slot.md
├── compare_builds.md
└── chat_followup.md
```

每个 prompt 构建应包含：

1. 基础系统原则
2. 当前任务 contract
3. 当前 `MatchContext`
4. 默认 baseline 或参考缓存摘要
5. 对应 `(model, game, data_version)` 的 calibration summary
6. 用户语言偏好
7. 当前游戏标签：
   - `LoL PC`
   - `Wild Rift`
8. localization bundle：
   - 中文官方名
   - 中文黑话别名
   - 目标语言显示名（如果可用）

额外约束：

- prompt 中必须显式写出当前 `game`
- prompt 规则里必须强调不要混用 `LoL PC` 与 `Wild Rift`
- 若输出结构里包含 slug，必须保留 `lol-` / `wr-` 前缀
- 模型直接按目标语言输出最终结果，不再增加单独翻译节点

## 9. Tool 调用设计

模型可调用的工具只应暴露“读数据”的能力，不应直接暴露数据库或对象存储细节。

建议工具接口：

- `get_champion(game, slug)`
- `get_item(game, slug)`
- `get_rune(game, slug)`
- `batch_get_entities(game, entity_type, slugs)`
- `search_catalog(game, entity_type, query)`

不要给模型的工具：

- 任意 SQL 查询
- 任意对象存储路径读取
- admin 操作

这些内容应由服务层直接注入，而不是暴露成 model-visible tool：

- baseline build
- reference cache summary
- calibration summary
- localization bundle

## 10. Session Transcript 设计

虽然 DB 不保存 session event 明细，但 transcript JSON 应标准化。

## 10.1 推荐事件类型

- `user_action`
- `ai_run`
- `system_note`

## 10.2 `user_action` 粒度

建议记录这些动作：

- `set_context`
- `set_build_slot`
- `clear_build_slot`
- `set_runes`
- `request_score`
- `request_recommend_slot`
- `request_recommend_full`
- `request_explain_slot`
- `request_compare`
- `send_chat_message`

## 10.3 写入策略

推荐写法：

- run 开始时先 append 一条 `user_action`
- run 完成后 append 一条 `ai_run`
- 更新 `sessions.event_count`
- 覆盖写回 transcript JSON

v1 transcript 对象不需要做增量 patch，直接整文件覆盖即可。

## 11. 强缓存与参考缓存实现

## 11.1 强缓存

适用条件：

- 无 `environment.free_text`
- run type 属于可缓存集合
- 上下文可规范化

命中后行为：

- 返回缓存结果
- 仍然创建一条 `ai_runs`
- `cache_resolution = strong_hit`

## 11.2 参考缓存

适用条件：

- 有自由文本
- 结构化上下文可生成 `semantic_context_hash`

命中后行为：

- 不直接返回缓存结果
- 把缓存结果摘要塞到 prompt 中作为 `reference context`
- `cache_resolution = reference_used`

## 11.3 缓存更新策略

只有满足以下条件的新结果才写入强缓存：

- run 成功完成
- 无自由文本
- 输出结构化结果有效
- 对应 `run_type` 属于可缓存类型

## 12. Leaderboard 更新实现

## 12.1 更新触发条件

只有 `evaluate_build` run 才更新 leaderboard。

## 12.2 更新粒度

只更新：

- `own_champion + enemy_champion` 单英雄场景
- `own_champion + null_enemy` 无敌方英雄场景

如果输入是 `2-5` 个敌方英雄：

- 该 run 不进入 leaderboard

这和你的产品规则一致，也能避免维度爆炸。

## 12.3 更新流程

1. 从 `ai_runs.operation_context` 中提取 own champion 与 enemy list
2. 若 enemy count 为 0：
   - 更新 `enemy_champion_slug = null`
3. 若 enemy count 为 1：
   - 更新该单英雄 entry
4. 若 enemy count > 1：
   - 直接跳过
5. 新分数高于当前 `top_score` 时：
   - 覆盖 `top_run_id`
   - 覆盖 `top_user_id`
   - 覆盖 `top_username_snapshot`

## 13. Admin Job 实现

## 13.1 Baseline Precompute

输入：

- `game`
- `data_version`
- `provider/model`

流程：

1. 遍历全部 champion slug
2. 构造“无敌方英雄、无环境标签”的基础 context
3. 调用 `recommend_full_build` agent
4. 写 `baseline_builds`

## 13.2 Calibration Generation

输入：

- `data_version`
- models
- games

流程：

1. 分 batch 读取 catalog
2. 调用 calibration workflow
3. 写 calibration summary object
4. 写 `model_calibrations`

## 13.3 Benchmark Run

输入：

- `dataset_id`
- models

流程：

1. 读取 benchmark dataset
2. 对每个 case 和 model 执行对应 run
3. 用 grading 层打分
4. 写 `benchmark_runs` 和 `benchmark_results`

## 14. 配置设计

`core/config.py` 建议使用单一 `Settings` 类管理：

### 应用层

- `APP_ENV`
- `APP_HOST`
- `APP_PORT`
- `APP_SECRET`

### PostgreSQL

- `DATABASE_URL`

### Object Storage

- `S3_ENDPOINT`
- `S3_BUCKET`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_REGION`

### Data Loading

- `GAME_DATA_SOURCE`
- `GAME_DATA_LOCAL_ROOT`
- `GAME_DATA_S3_ROOT`
- `GAME_LOCALIZATION_ROOT`

### Auth

- `JWT_SIGNING_KEY`
- `CLERK_SECRET_KEY`
- `CLERK_JWKS_URL`
- `CLERK_ISSUER`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

### AI Providers

- `GOOGLE_API_KEY`
- `PRIMARY_REASONING_PROVIDER`
- `PRIMARY_REASONING_MODEL`
- `FAST_REASONING_PROVIDER`
- `FAST_REASONING_MODEL`
- `CALIBRATION_PROVIDER`
- `CALIBRATION_MODEL`

v1 默认值建议：

- `PRIMARY_REASONING_PROVIDER=google`
- `PRIMARY_REASONING_MODEL=gemini-3.1-pro`
- `FAST_REASONING_PROVIDER=google`
- `FAST_REASONING_MODEL=gemini-3.1-pro`
- `CALIBRATION_PROVIDER=google`
- `CALIBRATION_MODEL=gemini-3.1-pro`

## 15. 错误处理设计

建议定义三层错误：

## 15.1 Domain Error

例如：

- `InvalidMatchContextError`
- `UnsupportedEnvironmentTagError`
- `SessionOwnershipError`

## 15.2 Integration Error

例如：

- `ProviderTimeoutError`
- `StorageWriteError`
- `CatalogLoadError`

## 15.3 API Error

由 route/middleware 统一映射成：

- HTTP status code
- error code
- user-facing message

不要把 provider 原始错误直接暴露给前端。

## 16. 测试策略

## 16.1 单元测试

优先覆盖：

- canonical key 生成
- context 规范化
- environment tag 校验
- leaderboard 资格判断
- cache 命中判断

## 16.2 Repository 测试

用临时 PostgreSQL 或 testcontainers 覆盖：

- session CRUD
- ai_runs 查询
- cache lookup
- leaderboard update

## 16.3 Service 测试

mock 掉 provider 和 object storage，覆盖：

- strong cache hit
- reference cache hit
- run 成功/失败
- session 删除
- user 删除

## 16.4 API 集成测试

覆盖：

- auth exchange
- create session
- create AI run
- SSE event stream
- leaderboard read
- admin trigger

补充重点：

- `stream=true` 仅对 `explain_slot` / `chat_followup` 生效
- 结构化推荐类 run 默认走非流式

## 17. 开发顺序建议

建议按以下顺序推进：

## Phase 1: 基础设施

1. `core/config`
2. `db/session`
3. `SQLAlchemy models`
4. `Alembic`
5. `storage_service`

## Phase 2: 数据与认证

1. `GameDataRegistry`
2. `catalog_service`
3. `auth_service`
4. `GET /catalog/*`
5. `POST /auth/exchange`

## Phase 3: Session 与 Run 主链路

1. `session_service`
2. `ai_run_service`
3. `BaseLLMClient`
4. `recommend_full_build`
5. `recommend_slot`
6. `evaluate_build`
7. `SSE`

## Phase 4: 运营能力

1. `cache_service`
2. `leaderboard_service`
3. `history API`
4. `session deletion`

## Phase 5: 离线能力

1. `baseline precompute`
2. `calibration workflow`
3. `benchmark workflow`
4. `admin jobs`

## 18. v1 明确不做的实现复杂度

为了保持速度，v1 不建议做：

- Redis 分布式缓存
- Celery / RabbitMQ
- 多 worker service
- prompt template 管理后台
- 实时 dashboard
- object storage 分块写入

这些都能以后补，但现在会明显拉长首个可用版本时间。

## 19. 推荐的首批交付物

如果按工程任务拆，第一批应该交付：

1. `FastAPI skeleton`
2. `DB migrations`
3. `catalog loader`
4. `auth exchange`
5. `session CRUD`
6. `ai run pipeline`
7. `SSE streaming`
8. `object artifact writer`
9. `cache lookup/write`
10. `leaderboard read/update`

这批完成后，PentaBuilder 的核心价值就已经可演示。
