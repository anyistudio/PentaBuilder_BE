# PentaBuilder Backend Step-by-Step TODO

## 1. 使用方式

这份文档不是“想法列表”，而是建议你实际执行的后端开发顺序。

目标：

1. 先尽快跑通主链路。
2. 再补缓存、排行榜、admin、benchmark。
3. 避免一开始就陷入次要复杂度。

建议执行原则：

- 每个阶段结束后都要有一个“可运行结果”。
- 不要同时开太多线。
- 先让 `catalog + auth + session + AI run` 跑通，再补运营功能。

## 2. 总体阶段

建议按这个顺序推进：

1. 项目骨架与开发环境
2. 基础设施与配置
3. Domain model 与 API schema
4. PostgreSQL schema 与 migration
5. 游戏数据加载与 catalog API
6. Auth 与 user API
7. Session 持久化
8. LLM provider 抽象与 tool layer
9. AI run 主链路
10. SSE streaming
11. 缓存系统
12. Leaderboard
13. Admin job
14. Baseline precompute
15. Calibration workflow
16. Benchmark workflow
17. 安全、日志、监控
18. 测试与上线准备

## 3. Phase 0: 项目骨架与开发环境

### TODO

- [x] 确定 Python 版本：`3.12`
- [x] 初始化后端包结构：
  - `app/`
  - `tests/`
  - `migrations/`
- [x] 确认包管理与运行入口统一使用 `uv`
- [x] 创建基础文件：
  - `pyproject.toml`
  - `.env.example`
  - `.gitignore`
- [x] 接入基础开发工具：
  - `ruff`
  - `pytest`
  - `mypy` 可选
- [x] 写一个最小 `FastAPI` 启动入口
- [x] 加一个 `/healthz` 接口

### Done 标准

- [x] `uv run uvicorn ...` 能启动
- [x] `GET /healthz` 返回 200
- [x] `uv run ruff check` 和 `uv run pytest` 都能跑

## 4. Phase 1: 基础设施与配置

### TODO

- [x] 实现 `core/config.py`
- [x] 定义环境变量：
  - `DATABASE_URL`
  - `S3_ENDPOINT`
  - `S3_BUCKET`
  - `S3_ACCESS_KEY`
  - `S3_SECRET_KEY`
  - `S3_REGION`
  - `GOOGLE_API_KEY`
  - `JWT_SIGNING_KEY`
  - `CLERK_SECRET_KEY`
  - `CLERK_JWKS_URL`
  - `CLERK_ISSUER`
  - `ADMIN_USERNAME`
  - `ADMIN_PASSWORD`
  - `PRIMARY_REASONING_PROVIDER`
  - `PRIMARY_REASONING_MODEL`
  - `FAST_REASONING_PROVIDER`
  - `FAST_REASONING_MODEL`
  - `CALIBRATION_PROVIDER`
  - `CALIBRATION_MODEL`
  - `GAME_DATA_SOURCE`
  - `GAME_DATA_LOCAL_ROOT`
  - `GAME_DATA_S3_ROOT`
  - `GAME_LOCALIZATION_ROOT`
- [x] 实现 `core/logging.py`
- [x] 实现 request id middleware
- [x] 定义统一错误模型：
  - domain error
  - integration error
  - api error
- [x] 定义核心常量和枚举：
  - `game`
  - `run_type`
  - `language`
  - `terminology_style`
  - `run_status`

### Done 标准

- [x] 配置从 `.env` 正常加载
- [x] 所有请求日志里带 `request_id`
- [x] 未捕获异常会被统一包装成 JSON error response

## 5. Phase 2: Domain Model 与 API Schema

### TODO

- [x] 在 `domain/` 里实现：
  - `MatchContext`
  - `ResponsePreferences`
  - `SessionEvent`
  - `canonicalize_enemy_comp`
  - `canonicalize_environment_tags`
  - `build_semantic_context_hash`
  - `build_response_variant_hash`
- [x] 在 `api/schemas/` 里实现 Pydantic request/response model：
  - auth schemas
  - catalog schemas
  - session schemas
  - ai run schemas
  - leaderboard schemas
  - admin schemas
- [x] 把 `environment tags` 白名单定成常量
- [x] 白名单固定为：
  - `aram`
  - `ranked`
  - `normal`
  - `tank-heavy`
  - `assassin-heavy`
  - `healing-heavy`
  - `ap-heavy`
  - `ad-heavy`
  - `cc-heavy`
  - `poke-heavy`
  - `early-game`
  - `late-game`
- [x] 明确输入校验：
  - enemy hero 数量 0-5
  - slot index 0-5
  - score 0-100
  - slug 前缀必须和 `game` 一致：
    - `lol-*` 对应 `lol`
    - `wr-*` 对应 `wild_rift`

### Done 标准

- [x] 所有 API 都有明确 Pydantic schema
- [x] canonical key 逻辑有单元测试

## 6. Phase 3: PostgreSQL Schema 与 Migration

### TODO

- [x] 初始化 SQLAlchemy Base 和 session factory
- [x] 建立这些 model：
  - `users`
  - `data_versions`
  - `sessions`
  - `ai_runs`
  - `baseline_builds`
  - `cached_context_results`
  - `leaderboard_entries`
- [x] 建 Alembic 初始化
- [x] 写第一批 migration
- [x] 建 repository：
  - `users_repository`
  - `data_versions_repository`
  - `sessions_repository`
  - `ai_runs_repository`
  - `cache_repository`
  - `leaderboard_repository`
- [x] 写数据库连接的 smoke test

### Done 标准

- [x] 本地数据库可迁移成功
- [x] repository 基础 CRUD 可测试通过
- [x] `leaderboard_entries` 的唯一索引正确处理 `NULL enemy`

## 7. Phase 4: 游戏数据加载与 Catalog API

### TODO

- [x] 实现 `storage_service` 的基础读能力
- [x] 实现 `data_version_service.get_active_version()`
- [x] 实现 `GameDataRegistry`
- [x] 支持从本地和 S3 两种来源读取：
  - `champions.json`
  - `items.json`
  - `runes.json`
  - `manifest.json`
- [x] 构建内存索引：
  - by slug
  - by normalized name
  - by alias
- [x] 增加本地化映射层：
  - `en`
  - `zh-CN official`
  - `zh-CN slang`
- [x] 单独生成可人工修订的 localization asset
- [x] 统一 slug canonical 规则：
  - `lol-*`
  - `wr-*`
- [x] 实现 catalog service
- [x] 实现 API：
  - `GET /catalog/versions/current`
  - `GET /catalog/{game}/champions`
  - `GET /catalog/{game}/items`
  - `GET /catalog/{game}/runes`
  - `GET /catalog/{game}/lookup`

### Done 标准

- [x] 可以在 API 层看到当前 active `data_version`
- [x] lookup 能同时搜英文、中文官方名、中文黑话

## 8. Phase 5: Auth 与 User API

### TODO

- [x] 接入 Clerk
- [x] 实现 `auth_service`
- [x] 实现 `POST /auth/exchange`
- [x] 实现后端 JWT/access token 签发与校验
- [x] 实现 `GET /me`
- [x] 实现 `PATCH /me/preferences`
- [x] 增加 auth dependency：
  - optional user
  - required user
  - admin user
- [x] admin 鉴权直接读取环境变量：
  - `ADMIN_USERNAME`
  - `ADMIN_PASSWORD`

### Done 标准

- [x] Clerk 登录交换成功
- [x] admin 固定账号密码可访问 admin API
- [x] 登录后能拿到 `/me`

## 9. Phase 6: Session 持久化

### TODO

- [x] 实现 `session_service.create_session`
- [x] 实现 `session_service.get_session`
- [x] 实现 `session_service.list_sessions`
- [x] 实现 `session_service.claim_session`
- [x] 明确 v1 匿名用户不自动创建后端持久化 session
- [x] 设计并实现 transcript JSON 结构
- [x] 实现 transcript object 的创建、覆盖更新、删除
- [x] 实现 API：
  - `POST /sessions`
  - `GET /sessions`
  - `GET /sessions/{id}`
  - `DELETE /sessions/{id}`
  - `POST /sessions/{id}/claim`

### Done 标准

- [x] 登录用户可以创建 session
- [x] session transcript 会写入 bucket
- [x] 删除 session 时 transcript 和 run artifact 同步删除

## 10. Phase 7: LLM Provider 抽象与 Tool Layer

### TODO

- [x] 实现 `BaseLLMClient`
- [x] 实现 provider client：
  - `GeminiClient`
- [x] 接入 `LangGraph` 作为复杂 agentic workflow 的运行时
- [x] 统一返回结构：
  - final text
  - structured payload
  - token usage
  - cost
  - latency
- [x] 实现 streaming adapter
- [x] 从本地目录或 object storage 加载 localization asset
- [x] 实现 tool layer：
  - `get_champion`
  - `get_item`
  - `get_rune`
  - `batch_get_entities`
  - `search_catalog`

### Done 标准

- [x] 默认 Gemini provider 能完成一次最小请求
- [x] tool call 可以从内存 catalog 获取信息

## 11. Phase 8: AI Run 主链路

### TODO

- [x] 实现 `ai_run_service.create_run`
- [x] 实现 `OnlineRunGraph` 最小版本：
  - prepare_context
  - generate_result
  - validate_result
- [x] 支持 run type：
  - `evaluate_build`
  - `recommend_slot`
  - `recommend_full_build`
  - `explain_slot`
  - `compare_builds`
  - `chat_followup`
- [x] 实现 AI agent：
  - `evaluate_build_agent`
  - `recommend_build_agent`
  - `explain_slot_agent`
  - `compare_builds_agent`
  - `chat_followup_agent`
- [x] prompt builder 支持：
  - MatchContext
  - response preferences
  - calibration summary
  - baseline/reference summary
  - localization bundle
- [x] prompt 必须显式注入当前游戏标签：
  - `LoL PC`
  - `Wild Rift`
- [x] prompt 规则必须强调不要混用 `LoL PC` 和 `Wild Rift`
- [x] 模型直接按目标语言生成最终结果，不再增加单独翻译节点
- [x] run 完成后写：
  - `ai_runs`
  - run artifact object
- [x] 实现 `POST /ai/runs`
- [x] 实现 `GET /ai/runs/{run_id}`

### Done 标准

- [x] 非流式评分链路可用
- [x] 非流式推荐链路可用
- [x] `ai_runs` 元数据完整落库

## 12. Phase 9: SSE Streaming

### TODO

- [x] 定义 SSE event 类型：
  - `run_started`
  - `message_delta`
  - `tool_event`
  - `run_completed`
  - `run_failed`
- [x] 实现 `GET /ai/runs/{run_id}/events`
- [x] 把 provider 流式输出转成统一 event
- [x] 只对长文本回答型 run 开启正文流：
  - `explain_slot`
  - `chat_followup`
- [x] `message_delta` 只流最终给用户看的自然语言文本，不流部分 JSON
- [x] 完整结构化结果只放在 `run_completed`
- [x] 结构化推荐类 run 默认走非流式：
  - `evaluate_build`
  - `recommend_full_build`
  - `recommend_slot`
  - `compare_builds`
- [x] 处理 run 失败与连接中断
- [x] 确保流式模式和非流式模式共用一套 run pipeline

### Done 标准

- [x] 流式 `explain_slot` / `chat_followup` 可以逐字输出
- [x] 完成时能返回最终结构化结果

## 13. Phase 10: 缓存系统

### TODO

- [x] 实现 `cache_service.lookup_strong_cache`
- [x] 实现 `cache_service.lookup_reference_cache`
- [x] 实现 `cache_service.save_cache_entry`
- [x] 只对以下 run type 启用缓存：
  - `evaluate_build`
  - `recommend_slot`
  - `recommend_full_build`
  - `explain_slot`
  - `compare_builds`
- [x] 规则落地：
  - 无 free text 才能强缓存
  - 有 free text 只能参考缓存
- [x] `ai_runs.cache_resolution` 正确写入：
  - `miss`
  - `strong_hit`
  - `reference_used`
  - `bypass`
- [x] 提供 admin cache clear 能力

### Done 标准

- [x] 相同结构化请求可直接命中强缓存
- [x] 带自由文本请求会把缓存结果作为模型参考，而不是直接返回

## 14. Phase 11: Leaderboard

### TODO

- [x] 实现 `leaderboard_service.update_from_run`
- [x] 只允许这些场景进 leaderboard：
  - 无敌方英雄
  - 单个敌方英雄
- [x] 多敌方英雄请求直接跳过 leaderboard
- [x] 实现 `GET /leaderboard`
- [x] 实现 `GET /leaderboard/{game}/{own_champion_slug}`
- [x] 用户删除/session 删除后可重算受影响 leaderboard

### Done 标准

- [x] 一个评分 run 成功后能刷新对应 leaderboard entry
- [x] 历史最高分用户会被正确展示

## 15. Phase 12: Admin Job

### TODO

- [x] 建 `admin_job_runs` 表和 model
- [x] 实现 admin auth
- [x] 实现 API：
  - `POST /admin/data-versions/activate`
  - `POST /admin/cache/clear`
  - `POST /admin/jobs/precompute-baselines`
  - `POST /admin/jobs/generate-calibrations`
  - `POST /admin/jobs/run-benchmarks`
  - `GET /admin/jobs/{job_id}`
- [x] 实现 job runner 记录：
  - requested_by
  - payload
  - status
  - summary

### Done 标准

- [x] admin 能手动触发版本切换和缓存清理
- [x] 每个 job 都有可查询的状态

## 16. Phase 13: Baseline Precompute

### TODO

- [x] 实现 `jobs/baselines.py`
- [x] 遍历某个 game + data_version 下全部 champion
- [x] 构造“无敌方英雄、无自由文本环境”的 context
- [x] 调用 `recommend_full_build`
- [x] 写入 `baseline_builds`
- [x] 允许重复执行时覆盖旧 baseline

### Done 标准

- [x] 所有英雄的基础默认 build/runes 可被批量预生成
- [x] catalog tool 可读取 baseline 并给在线 agent 使用

## 17. Phase 14: Calibration Workflow

### TODO

- [x] 建 `model_calibrations` 表和 model
- [x] 实现 `jobs/calibrations.py`
- [x] 读取当前 `data_version` 的 champions/items/runes
- [x] 按 batch 输入模型
- [x] 收集差异并生成 calibration summary
- [x] 把 summary 存 object storage
- [x] 在在线 AI pipeline 里自动附加对应 calibration summary

### Done 标准

- [x] 对每个 `(model, game, data_version)` 能生成一条 calibration 记录
- [x] 在线 run 能引用到对应 calibration summary

## 18. Phase 15: Benchmark Workflow

### TODO

- [x] 建表：
  - `benchmark_datasets`
  - `benchmark_cases`
  - `benchmark_runs`
  - `benchmark_results`
- [x] 实现 benchmark dataset loader
- [x] 实现 case grader
- [x] 实现 `jobs/benchmarks.py`
- [x] 支持首批候选模型：
  - `GPT-5.4-xhigh`
  - `GPT-5.4-medium`
  - `GPT-5.4-mini-xhigh`
  - `GPT-5.4-mini-medium`
  - `Gemini-3.1-pro`
  - `Gemini-3-flash`
  - `Gemini-2.5-flash`
- [x] 聚合输出：
  - accuracy
  - latency
  - cost

### Done 标准

- [x] 能对一个 dataset 完成一轮多模型 benchmark
- [x] 能输出模型横向对比结果

## 19. Phase 16: 安全、日志、监控

### TODO

- [x] 做输入长度限制
- [x] 做 environment tag 白名单校验
- [x] 做 free text 基本清洗
- [x] 做 prompt injection 基本 guardrail
- [x] admin API 权限校验
- [x] 记录日志字段：
  - `request_id`
  - `user_id`
  - `session_id`
  - `run_id`
  - `model_name`
  - `latency_ms`
  - `cost_usd`
  - `cache_resolution`
- [x] 输出关键 metrics：
  - 请求成功率
  - token/cost
  - 模型延迟
  - 缓存命中率

### Done 标准

- [x] 日志可追踪到单次 run
- [x] 能按模型和 run_type 做基础运营统计

## 20. Phase 17: 测试与上线准备

### TODO

- [x] 单元测试：
  - canonicalization
  - hash key
  - leaderboard eligibility
  - cache eligibility
- [x] repository 测试
- [x] service 测试
- [x] API integration 测试
- [x] SSE integration 测试
- [x] object storage mock 测试
- [x] provider mock 测试
- [x] 准备 Railway 部署配置
- [x] 准备 `dev` 和 `prod` 环境变量
- [x] 本地跑一轮完整 smoke flow：
  - current version
  - lookup champion
  - login
  - create session
  - recommend slot
  - evaluate build
  - list sessions
  - read leaderboard

### Done 标准

- [x] 本地 dev 环境全流程可跑
- [x] Railway dev 可部署
- [x] 最小产品闭环可演示

## 21. 推荐的实际执行顺序

如果你希望更细一点，我建议你按下面这个真实顺序做，不要跳：

1. 搭 FastAPI skeleton
2. 接配置、日志、错误处理
3. 上 PostgreSQL + Alembic
4. 实现 `users / data_versions / sessions / ai_runs`
5. 接 object storage
6. 实现 `GameDataRegistry`
7. 先把 catalog API 跑通
8. 接 auth
9. 实现 session CRUD
10. 先做非流式 `recommend_full_build`
11. 再做 `recommend_slot`
12. 再做 `evaluate_build`
13. 再做 `explain_slot`
14. 再做 `compare_builds`
15. 再做 `chat_followup`
16. 接 SSE streaming
17. 接强缓存和参考缓存
18. 接 leaderboard
19. 接 admin job
20. 接 baseline precompute
21. 接 calibration workflow
22. 接 benchmark workflow
23. 做测试、清理、部署

## 22. 哪些事情不要一开始做

这些先不要碰：

- Redis
- Celery
- 多服务拆分
- Prompt version 平台
- Public share link
- 复杂权限系统
- 复杂前端实时协作

这些都不是当前后端闭环必须项。

## 23. 我建议你第一周至少完成什么

如果你要压缩成第一周目标，我建议只追这 8 件事：

1. FastAPI skeleton
2. config/logging/error handling
3. PostgreSQL + Alembic
4. object storage client
5. `data_versions` + `GameDataRegistry`
6. catalog API
7. auth exchange
8. session create/list/get/delete

这周结束后，你就会有一个真正可继续堆功能的骨架。
