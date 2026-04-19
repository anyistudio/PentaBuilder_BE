# PentaBuilder Backend AI Workflow Reference

这份文档是面向当前代码实现的工作流说明，不是抽象设计稿。

如果你想知道后端里的 AI 请求到底怎么跑、每个 run type 会不会用工具、哪些 workflow 支持流式输出、离线 job 如何复用在线能力，这份文档以当前实现为准。

主要对应代码：

- `app/api/routes/ai.py`
- `app/services/ai_run_service.py`
- `app/ai/graphs/online_run_graph.py`
- `app/ai/graphs/nodes.py`
- `app/ai/orchestration/prompt_builder.py`
- `app/ai/orchestration/result_contracts.py`
- `app/ai/orchestration/tool_plans.py`
- `app/jobs/baselines.py`
- `app/jobs/calibrations.py`
- `app/jobs/benchmarks.py`
- `app/services/admin_job_service.py`

## 1. Workflow Inventory

### 1.1 在线 AI workflow

当前在线 run type 固定为 7 个：

| Run Type | 主要用途 | 默认模型 | 是否支持流式输出 |
| --- | --- | --- | --- |
| `evaluate_build` | 评价当前出装并给出更优方向 | primary reasoning model | 否 |
| `recommend_full_build` | 生成完整 build order + runes | primary reasoning model | 是 |
| `recommend_slot` | 只推荐单个槽位的最佳装备 | primary reasoning model | 否 |
| `explain_slot` | 解释当前槽位为什么好/不好，以及更优替代 | primary reasoning model | 是 |
| `compare_builds` | 比较 Build A 和 Build B 谁更优 | primary reasoning model | 否 |
| `game_status` | 估算击杀节奏、推塔节奏和原因 | primary reasoning model | 否 |
| `chat_followup` | 基于当前上下文做追问回答 | fast reasoning model | 是 |

说明：

- 除 `chat_followup` 外，在线 run 默认都走 `primary_reasoning_provider/model`。
- `chat_followup` 默认走 `fast_reasoning_provider/model`。
- `provider_name_override` / `model_name_override` 只在内部 job、benchmark 或显式覆盖时使用。

### 1.2 离线 AI workflow

当前后端里真正的离线 AI workflow 有 3 条：

| Workflow | 入口 | 是否复用在线 graph |
| --- | --- | --- |
| `precompute_baselines` | `/api/v1/admin/jobs/precompute-baselines` | 是 |
| `generate_calibration` | `/api/v1/admin/jobs/generate-calibrations` | 否 |
| `run_benchmarks` | `/api/v1/admin/jobs/run-benchmarks` | 是 |

说明：

- `activate_version` 和 `clear_cache` 是 admin job，但不属于 AI workflow。

## 2. 在线 Workflow 的统一执行路径

所有在线 AI 请求都从同一个 API 入口进入：

- `POST /api/v1/ai/runs`

同步和流式请求都先经过同一个 `create_run()`，区别只是后续执行路径不同。

### 2.1 API 层入口

`app/api/routes/ai.py#create_ai_run` 会做 3 件事：

1. 调用 `AIRunService.create_run(...)` 创建一条 `AIRun` 记录，并顺便决定是否直接命中强缓存。
2. 如果请求是流式模式：
   - 初始化事件流；
   - 用 FastAPI `BackgroundTasks` 异步启动 `execute_streaming_run(...)`；
   - 立即返回 `202 + stream_url`。
3. 如果请求是同步模式：
   - 直接在当前请求里调用 `execute_run(...)`；
   - 返回结构化结果。

### 2.2 `create_run()` 统一预处理

`AIRunService.create_run()` 是所有在线 workflow 的公共前置阶段。

它会按顺序做这些事情：

1. 检查当前 run type 是否允许 `stream=true`。
   - 当前只允许：
     - `recommend_full_build`
     - `explain_slot`
     - `chat_followup`
2. 校验 `operation_context`。
   - `recommend_slot` / `explain_slot` 必须有合法 `slot_index`
   - `compare_builds` 必须有合法的 `comparison_context`
   - `chat_followup` 必须有 `user_message`，可选 `reply_to_run_id`
   - `game_status` 会校验当前塔目标信息
3. 绑定 `session_id`。
   - 如果请求带会话，就校验会话存在、归属用户一致、游戏类型一致。
4. 生成两个 hash：
   - `semantic_context_hash`
   - `response_variant_hash`
5. 查缓存。
   - 强缓存：按 `response_variant_hash` 命中后可以直接返回结果
   - 参考缓存：按 `semantic_context_hash` 命中后不会直接返回，但会把旧 summary 注入 prompt
6. 创建并持久化一条 `AIRun` 记录。

### 2.3 `_prepare_run()` 统一装配阶段

真正进入模型或 graph 之前，`AIRunService._prepare_run()` 负责把所有运行材料准备好。

它会装配这些内容：

1. `CatalogSnapshot`
   - 根据 `data_version` 加载真实游戏数据快照。
2. baseline build
   - 从 `BaselineBuild` 里读取当前英雄的预计算 baseline。
3. calibration summary
   - 从 `ModelCalibration` 里读取当前 `provider/model/game/data_version` 最近一条已完成校准摘要。
4. reference cache summary
   - 只有命中 reference cache 时才注入。
5. session memory summary
   - 只有 `chat_followup` 且绑定 session 时才注入。
6. reply-to run summary
   - 只有 `chat_followup` 且给了 `reply_to_run_id` 时才注入。
7. 主 LLM client
   - 按 run type 默认模型或 override 创建。
8. selector LLM client
   - 用于 `resolve_catalog_slug` 这样的工具内子流程；默认使用 fast model。
9. `OnlineRunGraph`
   - 在线 workflow 全部共享同一张 graph，只是 run type 参数不同。

### 2.4 在线 Graph 主流程

`OnlineRunGraph` 的固定节点顺序如下：

1. `prepare_context`
2. `decide_tool_need`
3. `tool_select`（可选）
4. `tool_execute`（可选，可循环）
5. `generate_result`
6. `validate_result`
7. `repair_result`（只在校验失败时最多走一次）

用文字描述它的控制流就是：

1. 先把 state 里的上下文标准化并补默认值。
2. 判断当前 run type 是否需要工具，或者是否已经达到工具轮次上限。
3. 如果需要工具，让模型先输出一个最小 tool plan。
4. 执行工具，把工具结果收集成 `tool_facts`。
5. 重新判断是否还需要工具。
6. 工具阶段结束后，开始正式结构化生成结果。
7. 对结果做 schema + slug + contract 校验。
8. 如果只是 provider 输出结构轻微不合法，进入一次 repair。
9. 校验通过后，写入结果、artifact、cache、metrics、session event。

## 3. 在线 Graph 的每个节点在做什么

### 3.1 `prepare_context`

这个节点不做业务推理，只负责把运行时 state 规范成 graph 后续节点统一使用的结构。

它会保留或初始化这些字段：

- `context`
- `operation_context`
- `streamed_text`
- `tool_round_count`
- `total_tool_calls`
- `tool_trace`
- `tool_facts`
- `seen_tool_call_keys`
- `pending_tool_calls`
- `tool_context_ready`
- `retry_tool_planning`
- `provider_usage_payloads`
- `repair_attempt_count`
- `validation_errors`

### 3.2 `decide_tool_need`

这个节点只决定一件事：现在要不要进入工具规划。

它的判断顺序是：

1. 如果 `tool_context_ready=true`，直接跳过工具。
2. 如果已经达到本 run type 的最大工具轮次，也停止工具阶段。
3. 如果总工具调用数达到全局上限 `8`，也停止工具阶段。
4. 如果上一次 tool planning 因无效参数被要求重试，就强制再进一次 `tool_select`。
5. 否则按 run type 的默认规则判断。

当前每个 run type 的工具轮次上限：

| Run Type | 最大工具轮次 |
| --- | --- |
| `evaluate_build` | 2 |
| `recommend_full_build` | 4 |
| `recommend_slot` | 3 |
| `explain_slot` | 3 |
| `compare_builds` | 3 |
| `game_status` | 1 |
| `chat_followup` | 4 |

### 3.3 `tool_select`

这个节点会让模型输出一份严格 JSON 的最小 tool plan，而不是直接让模型自由调用工具。

这里的关键点是：

1. prompt 切到 `output_mode="tool_plan"`。
2. 返回 schema 固定为：
   - `reasoning_summary`
   - `tool_calls`
   - `done`
3. 一轮最多允许模型规划 2 个 tool call。
4. 所有工具参数都会再经过后端 sanitize。

sanitize 的目的有两个：

- 过滤不合法参数或不存在的 slug
- 去重，防止模型重复打同一个工具

如果模型规划了工具，但 sanitize 后一个有效调用都不剩：

- graph 不会直接失败；
- 会把 `retry_tool_planning=true`；
- 下一轮重新让模型规划，但提示它先用 `resolve_catalog_slug` 或更保守的候选列表工具。

### 3.4 `tool_execute`

这个节点顺序执行 `pending_tool_calls`。

执行结果会累积到：

- `tool_trace`
- `tool_facts`
- `seen_tool_call_keys`
- `provider_usage_payloads`

完成后：

- `tool_round_count += 1`
- `total_tool_calls += 本轮执行数`
- 再回到 `decide_tool_need`

### 3.5 `generate_result`

工具阶段结束后，正式进入结果生成。

它会：

1. 组装完整 prompt
2. 读取当前 run type 的结构化输出 schema
3. 调用模型返回 JSON
4. 把原始结果暂存在：
   - `model_result`
   - `result`
5. 把本轮 token / latency 信息并入 `provider_usage_payloads`

### 3.6 `validate_result`

这个节点不是单纯的 JSON schema 校验，它会做更强的“业务合同校验”。

包括但不限于：

- slug 是否真实存在于当前 game/data_version
- build 长度是否符合游戏规则
- `slot_index` 是否和请求完全一致
- build order 是否保留已填槽位
- `game_status` 是否覆盖了当前上下文中的所有敌方英雄
- `assumed_match_duration_minutes` 是否严格等于模式要求

如果校验通过：

- 会把 provider usage 聚合成 `_provider_usage`
- 写回 `final_result`

如果校验失败：

- 只有 provider 结构类错误且 repair 次数还没用完，才会进入 `repair_result`
- 否则直接抛出错误

### 3.7 `repair_result`

repair 不是重新跑整条 workflow，而是用已经有的上下文做一次“结构修复”。

它会：

1. 把 `output_mode` 切到 `repair_json`
2. 把 validation errors 和 candidate result 一起喂给模型
3. 让模型只修 schema / slug / enum / slot / contract 问题
4. 修完以后再回到 `validate_result`

当前最多只允许 1 次 repair。

## 4. 当前暴露给模型的工具

当前在线 workflow 只能访问 catalog 工具层，不能任意查数据库或文件。

对模型暴露的工具固定为：

- `get_champion`
- `get_item`
- `get_rune`
- `batch_get_entities`
- `search_catalog`
- `list_catalog_candidates`
- `list_item_ids`
- `resolve_catalog_slug`

这些工具全部由 `CatalogToolset` 提供，目标是拿“少量、结构化、可落地”的 grounded facts。

`resolve_catalog_slug` 比较特别：

- 它是工具内部的子流程，不是主 graph 的单独节点。
- 当模型不确定中文名、别名、近似 slug 或模糊写法时，应该优先通过它把名称解析成 canonical slug。
- 内部 ranking 会结合 deterministic lexical score 和 `fuzzywuzzy` 的多种分数做综合排序。
- 如果 item 名字还是摇摆不定，可以先用 `list_item_ids` 按 `physical`、`magic`、`boots`、`enchant` 这类大类把真实 ID 列出来。

## 5. 每个在线 Workflow 的详细流程

## 5.1 `evaluate_build`

用途：

- 评价当前 build 是否合理
- 给出更优 build / runes 方向
- 结果会同步到 leaderboard

请求 payload：

- 不需要额外 payload

默认工具策略：

- 如果当前 `own_build` 已填槽位少于 3 个，且存在敌方英雄，则允许用工具
- 否则认为注入上下文已经足够

结果合同：

- `score`
- `summary`
- `strengths`
- `weaknesses`
- `recommended_build`
- `recommended_runes`

后处理与副作用：

- 结果会被规范成统一的 `build` / `runes` / `explanations`
- `strengths` / `weaknesses` 会变成 explanation 列表
- run 完成后会更新 leaderboard

适用场景：

- 用户已经填了一套现有 build，想知道这套 build 在当前对局里的优缺点

## 5.2 `recommend_full_build`

用途：

- 生成完整 build order 和 rune 配置

请求 payload：

- 不需要额外 payload

默认工具策略：

- 如果已经有 baseline，敌方人数不超过 1，且没有 `free_text` 环境补充，则默认直接基于注入上下文生成
- 其他情况会开启工具比较候选项

结果合同：

- `recommended_build_order`
- `recommended_runes`
- `summary`
- `slot_notes`

特殊约束：

- LoL PC 必须返回 6 步
- Wild Rift 必须返回 7 步
- Wild Rift 的 boots 必须在 enchant 之前
- 不能覆盖用户当前已经填好的槽位

流式输出：

- 支持
- 流式可见文本通道是 `summary`

额外复用：

- 离线 `precompute_baselines` workflow 直接复用这个在线 run type

## 5.3 `recommend_slot`

用途：

- 只推荐某一个槽位该出什么装备

请求 payload：

- `slot_index`

默认工具策略：

- 始终允许工具

结果合同：

- `slot_index`
- `recommended_item_slug`
- `summary`
- `reasoning`
- `alternatives`

特殊约束：

- 返回的 `slot_index` 必须严格等于请求里的目标槽位
- 校验后只允许修改目标槽位，其他槽位不能变

适用场景：

- 用户已经有 build 框架，只想问“第 3 格应该补什么”

## 5.4 `explain_slot`

用途：

- 判断当前某个槽位的现有选择是否合理
- 如有必要，指出更好的替代项

请求 payload：

- `slot_index`

默认工具策略：

- 始终允许工具

结果合同：

- `slot_index`
- `current_item_slug`
- `is_current_choice_good`
- `best_item_slug`
- `summary`
- `why_current_choice`
- `why_best_choice`
- `linked_adjustments`

特殊约束：

- `current_item_slug` 如果返回非空，必须和当前上下文注入的槽位物品一致
- `best_item_slug` 必须是合法 item slug

流式输出：

- 支持
- 流式可见文本通道是 `summary`

适用场景：

- 用户想知道“我这格现在出的装备到底对不对，为什么”

## 5.5 `compare_builds`

用途：

- 对比 Build A 和 Build B 哪个更适合当前对局

请求 payload：

- `comparison_context`
  - `own_build`
  - `own_runes`

默认工具策略：

- 先计算 Build A 和 Build B 的差异数
- 如果差异项大于 2，允许工具辅助比较
- 如果差异很少，默认不走工具

结果合同：

- `winner`
- `score_delta`
- `summary`
- `key_differences`
- `when_build_b_is_better`

后处理：

- 根据 `winner` 决定最终回填到统一输出里的 `build` / `runes`
- `key_differences` 会转成 explanation 列表

适用场景：

- 用户已经有两套方案，想知道哪套更适合当前敌方阵容和环境

## 5.6 `game_status`

用途：

- 估算当前对局在后续一段时间里的：
  - 我方对每个敌人的击杀频率
  - 敌方对我的击杀频率
  - 我方推塔速度
  - 各个敌人的推塔速度

请求 payload：

- `own_current_tower_target`
- `enemy_current_tower_targets`

默认工具策略：

- 默认不使用工具
- 认为 `Detailed Parameter Appendix + 当前上下文注入` 已经足够

结果合同：

- `summary`
- `assumed_match_duration_minutes`
- `own_kill_frequency_vs_enemies`
- `own_tower_push_percent_per_minute`
- `own_tower_push_reason`
- `enemy_statuses`

特殊约束：

- `assumed_match_duration_minutes` 必须严格等于：
  - `15`：ARAM
  - `30`：普通/排位
- `own_kill_frequency_vs_enemies` 必须完整覆盖当前所有敌方英雄，且不能重复
- `enemy_statuses` 也必须完整覆盖当前所有敌方英雄，且不能重复
- 击杀频率不能超过假定对局时长
- 返回结果里会附上当前参与实体的参数 appendix

prompt 侧的额外上下文：

- 当前我方塔目标
- 当前每个敌方的塔目标
- 面向 prompt 的 compact 参数附录
- 规则上强调“理由优先锚定当前已拥有装备，再解释装备与英雄机制、对线/团战关系”

补充说明：

- prompt 注入的 appendix 会去掉重复的本地化字段和过长的冗余元数据，减少 token 浪费
- 最终 API 返回里的 `parameter_appendix` 仍然保留 deterministic catalog snapshot，方便前端调试和展示

适用场景：

- 前端 timeline 每前进一分钟时，需要后端重新估算击杀和推塔节奏

## 5.7 `chat_followup`

用途：

- 基于已有上下文和上一个结果做用户追问

请求 payload：

- `user_message`
- 可选 `reply_to_run_id`

默认工具策略：

- 始终允许工具

模型选择：

- 默认走 fast reasoning model

结果合同：

- `summary`
- `answer`
- `followup_suggestions`

prompt 侧额外注入：

- 用户追问文本
- 可选 reply-to run summary
- 最近 session memory 摘要

流式输出：

- 支持
- 流式可见文本通道是 `answer`

缓存：

- 当前不走 `CACHEABLE_RUN_TYPES`

适用场景：

- 用户对推荐结果继续追问“为什么这件装备比那件更好”

## 6. 流式 Workflow 的特殊路径

只有 `recommend_full_build`、`explain_slot`、`chat_followup` 走流式路径。

它和同步路径的核心差别是：

1. 先调用 `collect_tool_context()`
   - 只把工具相关阶段跑完
2. 把 prompt 切到 `output_mode="stream_sections"`
3. 要求模型输出两段：
   - `<display>用户可见文本</display>`
   - `<json>最终结构化 JSON</json>`
4. SSE 过程中只把 `<display>` 里的可见文本增量发给前端
5. 流式结束后，再用 `finalize_existing_result()` 对 JSON 结果做 validate / repair
6. 如果分段流输出无法正确收尾：
   - 后端发一个 `tool_event` 说明 fallback
   - 然后回退到普通 `execute_run()`

如果命中了强缓存：

- 不会重新跑 graph
- 会直接重放缓存里的可见文本流

## 7. 离线 Workflow 的详细流程

## 7.1 `precompute_baselines`

入口：

- `/api/v1/admin/jobs/precompute-baselines`
- 后台由 `AdminJobService` 调度

执行步骤：

1. 读取目标 `data_version` 和 `game`
2. 加载对应 `CatalogSnapshot`
3. 枚举该游戏下全部英雄 slug
4. 对每个英雄构造一个最小 `MatchContext`
5. 调用在线 `recommend_full_build`
   - `create_run(..., use_cache=False)`
   - `execute_run(..., provider_name_override, model_name_override)`
6. 把结果 upsert 到 `BaselineBuild`
   - `recommended_build`
   - `recommended_runes`
   - `provider_name`
   - `model_name`
   - `source_run_id`

这个 workflow 的意义：

- 让在线请求可以直接拿到“当前英雄的基准 build 参考”
- baseline 会在不少 run type 的 prompt 中作为参考注入

## 7.2 `generate_calibration`

入口：

- `/api/v1/admin/jobs/generate-calibrations`

这是唯一一条“不复用在线 graph”的 AI workflow。

执行步骤：

1. 读取目标 `provider/model/game/data_version`
2. 直接创建对应 LLM client
3. 加载 `CatalogSnapshot`
4. 把 champions + items + runes 扁平化成一个实体列表
5. 每 40 个实体切成一个 batch
6. 对每个 batch 直接调用 `llm_client.generate_text(...)`
   - 不要求结构化 JSON
   - 目标是让模型指出“这些条目里哪些看起来和它内置知识不一致”
7. 汇总所有 batch note
8. 把全文写到对象存储：
   - `calibrations/{provider}/{model}/{game}/{data_version}/summary.txt`
9. upsert 一条 `ModelCalibration`
   - `summary_object_key`
   - `summary_excerpt`
   - `status=completed`

这个 workflow 的意义：

- 给在线 workflow 提供一个“模型知识可能过时的提醒摘要”
- 在线 prompt 会按当前模型版本加载对应 calibration summary

## 7.3 `run_benchmarks`

入口：

- `/api/v1/admin/jobs/run-benchmarks`

执行步骤：

1. 同步并读取 benchmark dataset
2. 按 case_key 取出全部 `BenchmarkCase`
3. 对每个待评测模型创建一条 `BenchmarkRun`
4. 对每个 case：
   - `BenchmarkService.build_case_request(case)`
   - `ai_run_service.create_run(..., use_cache=False)`
   - `ai_run_service.execute_run(..., provider/model override)`
   - `BenchmarkService.grade_case(...)`
   - 写入 `BenchmarkResult`
5. 汇总：
   - `accuracy_score`
   - `avg_case_score`
   - `avg_latency_ms`
   - `avg_cost_usd`
6. 把汇总写到对象存储：
   - `benchmarks/{benchmark_run.id}/summary.json`
7. 更新 `BenchmarkRun` 为 completed

这个 workflow 的意义：

- 它不是单独设计另一套推理逻辑
- 它的核心价值是“用同一套在线 workflow 对不同模型做可重复评测”

## 8. Workflow 完成后的统一落库与副作用

无论哪个在线 workflow，只要成功结束，都会走 `_complete_run()` / `_finalize_completed_run()` 这套收尾逻辑。

统一副作用包括：

1. 更新 `AIRun`
   - `status`
   - `provider_name`
   - `model_name`
   - token / latency / cost
   - `structured_result`
   - `artifact_object_key`
2. 写 artifact JSON 到对象存储
   - 包含 context、payload、tool_trace、tool_facts、result、prompt
3. 如果该 run type 可缓存，且上下文允许，就写强缓存
4. 如果绑定了 session，就把 run 结果追加进 transcript
5. 记录 metrics
6. 如果是 `evaluate_build`，更新 leaderboard

失败时则统一走 `_mark_run_failed()`：

- `status=failed`
- 写入 `error_code`
- 写入 `error_message`

## 9. 读代码时最值得优先看的顺序

如果以后要继续改 workflow，推荐按这个顺序读：

1. `app/api/routes/ai.py`
2. `app/services/ai_run_service.py`
3. `app/ai/graphs/online_run_graph.py`
4. `app/ai/graphs/nodes.py`
5. `app/ai/orchestration/prompt_builder.py`
6. `app/ai/orchestration/result_contracts.py`
7. `app/ai/tools/catalog_tools.py`
8. `app/jobs/baselines.py`
9. `app/jobs/calibrations.py`
10. `app/jobs/benchmarks.py`

这样看，最容易把“API 请求 -> graph -> prompt -> tool -> result contract -> offline 复用”整条链路一次串起来。
