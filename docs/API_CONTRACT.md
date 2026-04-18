# PentaBuilder Backend API Contract

## 1. 文档目标

这份文档定义 `PentaBuilder_BE` 对外暴露的 HTTP/SSE 接口契约。

目标：

1. 给前端一份稳定的接口规范。
2. 给后端一份可转成 Pydantic schema 和 OpenAPI 的草案。
3. 明确匿名试玩、登录用户、admin 用户三种权限边界。

这不是最终 OpenAPI 文件，但字段、路径、状态码和行为语义应尽量稳定。

## 2. 总体原则

## 2.1 Base Path

所有业务接口使用：

```text
/api/v1
```

## 2.2 数据格式

- 请求与响应主体使用 `application/json`
- 流式响应使用 `text/event-stream`
- 时间统一使用 ISO 8601 UTC 字符串

## 2.3 认证策略

前端通过 Clerk 完成登录后，调用：

- `POST /api/v1/auth/exchange`

后端验证 Clerk token，并返回后端 access token。

后续需要登录的接口都携带：

```text
Authorization: Bearer <backend_access_token>
```

## 2.4 权限分层

### 匿名可用

- catalog 读取
- 当前版本查询
- AI run 调用

### 登录后可用

- 保存/读取 session history
- leaderboard
- 个人资料修改
- 删除个人数据

### admin 可用

- 激活数据版本
- 清理缓存
- 触发离线 job

admin 接口不依赖 Clerk role；v1 直接使用环境变量中的固定管理员账号密码。

## 2.5 响应包装

推荐统一响应 envelope：

```json
{
  "request_id": "req_123",
  "data": {}
}
```

错误响应：

```json
{
  "request_id": "req_123",
  "error": {
    "code": "invalid_input",
    "message": "own_champion_slug is required",
    "details": {}
  }
}
```

## 3. 公共类型

## 3.1 枚举

### `game`

```json
"lol" | "wild_rift"
```

### `language`

```json
"zh-CN" | "en"
```

### `terminology_style`

```json
"official" | "slang_zh"
```

### `run_type`

```json
"evaluate_build"
"recommend_slot"
"recommend_full_build"
"explain_slot"
"compare_builds"
"game_status"
"chat_followup"
```

### `run_status`

```json
"accepted" | "streaming" | "completed" | "failed" | "cancelled"
```

### `cache_resolution`

```json
"miss" | "strong_hit" | "reference_used" | "bypass"
```

## 3.2 Match Context

```json
{
  "game": "lol",
  "data_version": "full-20260412",
  "own_champion_slug": "lol-ahri",
  "enemy_team": [
    {
      "champion_slug": "lol-zed",
      "build": ["lol-eclipse", null, null, null, null, null],
      "runes": {
        "primary": [],
        "secondary": []
      }
    },
    {
      "champion_slug": "lol-lee-sin",
      "build": [null, null, null, null, null, null],
      "runes": {
        "primary": [],
        "secondary": []
      }
    }
  ],
  "own_build": ["lol-luden-s-echo", null, null, null, null, null],
  "own_runes": {
    "primary": [],
    "secondary": []
  },
  "environment": {
    "tags": ["ranked", "assassin-heavy"],
    "free_text": "对面爆发高，前期压力很大"
  }
}
```

### 规则

- `game`、`data_version`、`own_champion_slug` 必填
- 所有 champion/item/rune slug 必须使用 canonical 前缀格式：
  - `lol-...` 对应 `LoL PC`
  - `wr-...` 对应 `Wild Rift`
- 即使 slug 自带前缀，`game` 仍然必须保留：
  - 后端用它校验 slug 是否属于正确游戏
  - 前端用它明确展示当前工作区到底是 `LoL PC` 还是 `Wild Rift`
- `enemy_team` 允许 0-5 个
- `enemy_team[*].champion_slug` 必填
- `enemy_team[*].build` 与 `enemy_team[*].runes` 可为空或部分填写
- `environment.tags` 只能来自后端白名单
- `environment.free_text` 可为空
- 后端会从 `enemy_team` 派生内部 canonical 字段 `enemy_champion_slugs_sorted`

### `environment.tags` 白名单

后端统一接受以下 canonical tag：

| canonical tag | 前端展示建议 |
|---|---|
| `aram` | `ARAM` |
| `ranked` | `Ranked` |
| `normal` | `Normal` |
| `tank-heavy` | `坦克多` |
| `assassin-heavy` | `刺客多` |
| `healing-heavy` | `回复多` |
| `ap-heavy` | `AP 多` |
| `ad-heavy` | `AD 多` |
| `cc-heavy` | `控制多` |
| `poke-heavy` | `消耗多` |
| `early-game` | `前期强势` |
| `late-game` | `后期发力` |

## 3.3 Response Preferences

```json
{
  "language": "zh-CN",
  "terminology_style": "slang_zh"
}
```

## 3.4 Session Summary

```json
{
  "id": "uuid",
  "title": "Ahri vs Zed",
  "game": "lol",
  "data_version": "full-20260412",
  "event_count": 12,
  "updated_at": "2026-04-12T20:00:00Z",
  "last_context_snapshot": {}
}
```

## 3.5 AI Run Summary

```json
{
  "id": "uuid",
  "run_type": "evaluate_build",
  "status": "completed",
  "cache_resolution": "strong_hit",
  "provider_name": "google",
  "model_name": "gemini-3.1-pro",
  "latency_ms": 1800,
  "score_value": 84,
  "created_at": "2026-04-12T20:05:00Z"
}
```

## 4. Auth API

## 4.1 `POST /api/v1/auth/exchange`

用途：

- 前端把第三方 provider token 交给后端
- 后端验证 token，并返回后端 access token

### Request

```json
{
  "provider": "clerk",
  "provider_token": "clerk-session-or-jwt"
}
```

### Response 200

```json
{
  "request_id": "req_123",
  "data": {
      "access_token": "backend-jwt",
      "token_type": "Bearer",
      "expires_in": 3600,
      "user": {
        "id": "uuid",
        "auth_provider": "clerk",
        "email": "user@example.com",
        "email_verified": true,
        "display_name": "Jialin",
      "username": "BlueFox",
      "icon_url": "https://...",
      "preferred_language": "zh-CN",
      "preferred_terminology_style": "official"
    }
  }
}
```

### 错误

- `400 invalid_provider`
- `401 invalid_provider_token`

补充说明：

- v1 普通用户 provider 固定为 `clerk`
- admin 接口不走这个 exchange 流程

## 4.2 `GET /api/v1/me`

用途：

- 获取当前登录用户资料

### Auth

- required

### Response 200

```json
{
  "request_id": "req_124",
  "data": {
    "id": "uuid",
    "auth_provider": "clerk",
    "email": "user@example.com",
    "email_verified": true,
    "display_name": "Jialin",
    "username": "BlueFox",
    "icon_url": "https://...",
    "preferred_language": "zh-CN",
    "preferred_terminology_style": "slang_zh"
  }
}
```

## 4.3 `PATCH /api/v1/me/preferences`

用途：

- 修改展示偏好和用户名

### Auth

- required

### Request

```json
{
  "username": "BlueFox",
  "preferred_language": "en",
  "preferred_terminology_style": "official"
}
```

### Response 200

返回更新后的用户对象。

## 4.4 `DELETE /api/v1/me`

用途：

- 删除当前用户及其持久化数据

### Auth

- required

### 行为

- 删除用户
- 删除其 session 与 run artifact
- 重算受影响 leaderboard

### Response 204

- no body

## 5. Catalog API

## 5.1 `GET /api/v1/catalog/versions/current`

用途：

- 获取当前激活的数据版本

### Response 200

```json
{
  "request_id": "req_200",
  "data": {
    "data_version": "full-20260412",
    "lol_patch_version": "25.7",
    "wild_rift_patch_version": "6.1",
    "activated_at": "2026-04-12T10:00:00Z"
  }
}
```

## 5.2 `GET /api/v1/catalog/versions`

用途：

- 获取可选版本列表

### Query

- `active_only` optional boolean

## 5.3 `GET /api/v1/catalog/{game}/champions`

## 5.4 `GET /api/v1/catalog/{game}/items`

## 5.5 `GET /api/v1/catalog/{game}/runes`

用途：

- 返回当前游戏的只读 catalog

### Path Params

- `game`: `lol` / `wild_rift`

### Query

- `data_version` optional；默认 current active version
- `language` optional
- `terminology_style` optional

### Response 200

```json
{
  "request_id": "req_201",
  "data": {
    "game": "lol",
    "data_version": "full-20260412",
    "items": [
      {
        "slug": "lol-luden-s-echo",
        "name": "卢登的回声",
        "aliases": ["卢登"],
        "icon_url": "https://..."
      }
    ]
  }
}
```

## 5.6 `GET /api/v1/catalog/{game}/lookup`

用途：

- 查询英雄/装备/符文

### Query

- `q` required
- `entity_type` optional: `champion` / `item` / `rune`
- `data_version` optional
- `language` optional
- `terminology_style` optional
- `limit` optional default `20`

## 6. Session API

补充规则：

- v1 匿名用户默认不自动创建后端持久化 session
- 匿名模式只维护本地 `client_session_id` 和本地 event buffer
- 登录后若用户选择保存当前工作区，再通过 `claim` 进入后端持久化层

## 6.1 `POST /api/v1/sessions`

用途：

- 为已登录用户创建持久化 session

### Auth

- required

### Request

```json
{
  "client_session_id": "client-uuid",
  "game": "lol",
  "data_version": "full-20260412",
  "initial_context": {
    "game": "lol",
    "data_version": "full-20260412",
    "own_champion_slug": "lol-ahri",
    "enemy_team": [],
    "own_build": [null, null, null, null, null, null],
    "own_runes": {
      "primary": [],
      "secondary": []
    },
    "environment": {
      "tags": [],
      "free_text": ""
    }
  }
}
```

### Response 201

```json
{
  "request_id": "req_300",
  "data": {
    "session": {
      "id": "uuid",
      "game": "lol",
      "data_version": "full-20260412",
      "event_count": 0,
      "created_at": "2026-04-12T20:10:00Z"
    }
  }
}
```

## 6.2 `GET /api/v1/sessions`

用途：

- 获取当前用户历史 session 列表

### Auth

- required

### Query

- `limit` default `20`
- `cursor` optional

## 6.3 `GET /api/v1/sessions/{session_id}`

用途：

- 获取某个 session 详情

### Auth

- required

### Response 200

```json
{
  "request_id": "req_301",
  "data": {
    "session": {
      "id": "uuid",
      "title": "Ahri vs Zed",
      "game": "lol",
      "data_version": "full-20260412",
      "event_count": 12,
      "updated_at": "2026-04-12T20:30:00Z",
      "last_context_snapshot": {}
    },
    "transcript": {
      "events": []
    }
  }
}
```

## 6.4 `DELETE /api/v1/sessions/{session_id}`

用途：

- 删除 session 及其对象存储原文

### Auth

- required

### Response 204

- no body

## 6.5 `POST /api/v1/sessions/{session_id}/claim`

用途：

- 匿名模式转登录后，把本地缓冲事件提交给后端并绑定到指定 session

### Auth

- required

### Request

```json
{
  "client_session_id": "client-uuid",
  "events": [
    {
      "type": "user_action",
      "action": "set_context",
      "timestamp": "2026-04-12T20:00:00Z",
      "payload": {}
    }
  ]
}
```

### Response 200

```json
{
  "request_id": "req_302",
  "data": {
    "session_id": "uuid",
    "claimed_event_count": 8
  }
}
```

## 7. AI Run API

## 7.1 设计原则

所有 AI 能力走同一个入口：

- `POST /api/v1/ai/runs`

原因：

- 后端逻辑统一
- 便于记录成本和缓存
- 便于 benchmark 与真实调用共用 run pipeline

## 7.2 `POST /api/v1/ai/runs`

用途：

- 创建一次 AI run

### Auth

- optional

### Request

```json
{
  "session_id": "optional-session-uuid",
  "run_type": "recommend_slot",
  "stream": false,
  "response_preferences": {
    "language": "zh-CN",
    "terminology_style": "slang_zh"
  },
  "context": {
    "game": "lol",
    "data_version": "full-20260412",
    "own_champion_slug": "lol-ahri",
    "enemy_team": [
      {
        "champion_slug": "lol-zed",
        "build": [null, null, null, null, null, null],
        "runes": {
          "primary": [],
          "secondary": []
        }
      }
    ],
    "own_build": ["lol-luden-s-echo", null, null, null, null, null],
    "own_runes": {
      "primary": [],
      "secondary": []
    },
    "environment": {
      "tags": ["ranked", "assassin-heavy"],
      "free_text": ""
    }
  },
  "payload": {
    "slot_index": 1
  }
}
```

### 通用规则

- 登录用户若传入 `session_id`，该 run 会进入持久化 session
- 匿名用户可以不传 `session_id`
- `stream=true` 适用于需要前端展示推理进度、tool call 和正文预览的 run：
  - `recommend_full_build`
  - `explain_slot`
  - `chat_followup`
- 对纯结构化结果为主的 run：
  - `evaluate_build`
  - `recommend_slot`
  - `compare_builds`
  - `game_status`
  不建议开启 SSE 正文流
- `stream=false` 时可直接返回完整结果
- 前端必须根据 `context.game` 明确展示当前工作区是 `LoL PC` 还是 `Wild Rift`

### 按 `run_type` 的附加要求

#### `evaluate_build`

- `payload` 可为空

#### `recommend_slot`

- `payload.slot_index` required
- `slot_index` 范围按 `game` 决定：
  - LoL PC: `0-5`
  - Wild Rift: `0-6`

#### `recommend_full_build`

- `payload` 可为空
- 返回结果中的 `recommended_build_order` 表示有序出装步骤
- LoL PC: 长度固定为 `6`
- Wild Rift: 长度固定为 `7`
- Wild Rift 的 `7` 步必须是 `5` 件普通装备 + `1` 双鞋子 + `1` 个独立附魔
- Wild Rift 中鞋子步骤必须早于附魔步骤

#### `explain_slot`

- `payload.slot_index` required

#### `compare_builds`

- `payload.comparison_context` required

示例：

```json
{
  "comparison_context": {
    "own_build": ["lol-luden-s-echo", "lol-zhonyas-hourglass", null, null, null, null],
    "own_runes": {
      "primary": [],
      "secondary": []
    }
  }
}
```

#### `game_status`

- `payload` 可为空
- 可选：
  - `payload.own_current_tower_target`
    - `"outer_tower" | "inner_tower" | "nexus"`
    - 不传时默认 `"outer_tower"`
  - `payload.enemy_current_tower_targets`
    - 数组，按敌方英雄逐个声明当前目标塔
    - 每项结构：

```json
{
  "champion_slug": "lol-zed",
  "tower_target": "outer_tower"
}
```

- 返回结果会包含：
  - `assumed_match_duration_minutes`
  - `own_kill_frequency_vs_enemies`
  - `own_tower_push_percent_per_minute`
  - `enemy_statuses`
- 若 `environment.tags` 包含 `aram`，`assumed_match_duration_minutes` 必须为 `15`
- 否则 `assumed_match_duration_minutes` 必须为 `30`
- 后端会额外追加一个 deterministic `parameter_appendix`
  - 包含当前涉及英雄、装备、符文的详细参数快照
  - 该 appendix 直接来自 catalog 数据，不依赖模型回填
- `own_tower_push_percent_per_minute` 表示“我方当前目标塔”每分钟推进多少百分比
- `enemy_statuses[*].tower_push_percent_per_minute` 表示“该敌方英雄当前目标塔”每分钟推进多少百分比

#### `chat_followup`

- `payload.user_message` required
- 可选 `payload.reply_to_run_id`

示例：

```json
{
  "user_message": "那这个位置为什么不出中娅？",
  "reply_to_run_id": "uuid"
}
```

### Response 202: streaming mode

```json
{
  "request_id": "req_400",
  "data": {
    "run": {
      "id": "uuid",
      "run_type": "chat_followup",
      "status": "accepted",
      "cache_resolution": "miss",
      "created_at": "2026-04-12T20:20:00Z"
    },
    "stream_url": "/api/v1/ai/runs/uuid/events"
  }
}
```

### Response 200: non-streaming mode

```json
{
  "request_id": "req_401",
  "data": {
    "run": {
      "id": "uuid",
      "run_type": "recommend_slot",
      "status": "completed",
      "cache_resolution": "strong_hit",
      "provider_name": "google",
      "model_name": "gemini-3.1-pro",
      "latency_ms": 1200,
      "created_at": "2026-04-12T20:20:00Z"
    },
    "result": {
      "score": null,
      "summary": "推荐第二件补中娅。",
      "build": ["lol-luden-s-echo", "lol-zhonyas-hourglass", null, null, null, null],
      "runes": null,
      "explanations": [
        {
          "target": "slot:1",
          "text": "对面 Zed 爆发高，中娅能显著提高容错。"
        }
      ],
      "alternatives": [
        {
          "target": "slot:1",
          "item_slug": "lol-banshees-veil",
          "reason": "如果对面主要是 AP 控制，可以考虑女妖。"
        }
      ]
    }
  }
}
```

### 错误

- `400 invalid_context`
- `400 invalid_payload`
- `400 stream_not_supported_for_run_type`
- `401 unauthorized_session`
- `404 session_not_found`
- `409 session_game_mismatch`
- `422 unsupported_environment_tag`
- `429 quota_exceeded` future use
- `502 provider_error`

## 7.3 `GET /api/v1/ai/runs/{run_id}`

用途：

- 获取单次 run 最终结果或当前状态

### Auth

- optional；但如果 run 属于某个用户，则需要 owner 或 admin

### Response 200

```json
{
  "request_id": "req_402",
  "data": {
    "run": {
      "id": "uuid",
      "session_id": "uuid",
      "run_type": "evaluate_build",
      "status": "completed",
      "cache_resolution": "reference_used",
      "provider_name": "google",
      "model_name": "gemini-3.1-pro",
      "tokens_input": 1450,
      "tokens_output": 320,
      "cost_usd": 0.018221,
      "latency_ms": 1980,
      "score_value": 84,
      "created_at": "2026-04-12T20:20:00Z"
    },
    "result": {
      "score": 84,
      "summary": "整体思路正确，但第二件装备不够稳。",
      "build": [],
      "runes": {},
      "explanations": []
    }
  }
}
```

## 7.4 `GET /api/v1/ai/runs/{run_id}/events`

用途：

- SSE 订阅某次 run 的实时事件

### Auth

- optional；但如果 run 属于某个用户，则需要 owner 或 admin

### Response

`Content-Type: text/event-stream`

### SSE Event Types

#### `run_started`

```text
event: run_started
data: {"run_id":"uuid","run_type":"chat_followup"}
```

#### `message_delta`

```text
event: message_delta
data: {"channel":"answer","language":"zh-CN","delta":"这一局更推荐先做"}
```

规则：

- `message_delta` 只流最终给用户看的自然语言文本，不流部分 JSON
- `channel` 建议固定为 `summary` 或 `answer`
- 前端应把它当成打字机文本流渲染
- 完整结构化结果只在 `run_completed` 事件里读取

#### `tool_event`

```text
event: tool_event
data: {
  "phase":"planning",
  "status":"ready",
  "summary":"Need item facts for the next spike comparison.",
  "tool_calls":[
    {"tool_name":"search_catalog","arguments":{"entity_type":"item","query":"stasis ap item","limit":5}}
  ]
}
```

规则：

- `tool_event` 会承载 planning / execution / drafting 三类阶段事件
- planning 事件可带 `summary` 与 `tool_calls`
- execution 事件可带 `tool`、`arguments`、`match_slugs`、`resolved_slugs`
- drafting 事件用于提示“开始流正文”与“正文预览结束”

#### `run_completed`

```text
event: run_completed
data: {
  "run_id":"uuid",
  "status":"completed",
  "cache_resolution":"miss",
  "result":{
    "score":84,
    "summary":"..."
  }
}
```

#### `run_failed`

```text
event: run_failed
data: {
  "run_id":"uuid",
  "status":"failed",
  "error":{
    "code":"provider_error",
    "message":"Gemini timeout"
  }
}
```

补充规则：

- `message_delta` 只在开启了 `stream=true` 的预览正文 run 中出现，当前主要是：
  - `recommend_full_build`
  - `explain_slot`
  - `chat_followup`
- `message_delta` 直接来自目标语言生成过程，不存在单独翻译阶段
- 即使前端实时显示了 `message_delta`，完整结构化结果仍以 `run_completed` 为准

## 8. Leaderboard API

## 8.1 `GET /api/v1/leaderboard`

用途：

- 获取当前版本 leaderboard

### Auth

- required

### Query

- `game` required
- `data_version` optional；默认当前 active version
- `own_champion_slug` optional
- `enemy_champion_slug` optional；为空表示不过滤
- `limit` optional default `50`
- `offset` optional default `0`

### Response 200

```json
{
  "request_id": "req_500",
  "data": {
    "game": "lol",
    "data_version": "full-20260412",
    "items": [
      {
        "own_champion_slug": "lol-ahri",
        "enemy_champion_slug": "lol-zed",
        "top_score": 95,
        "top_user": {
          "id": "uuid",
          "username": "BlueFox"
        },
        "top_run_id": "uuid",
        "updated_at": "2026-04-12T20:00:00Z"
      }
    ],
    "pagination": {
      "limit": 50,
      "offset": 0
    }
  }
}
```

## 8.2 `GET /api/v1/leaderboard/{game}/{own_champion_slug}`

用途：

- 获取某个我方英雄的 leaderboard 视图

### Auth

- required

### Query

- `data_version` optional

## 9. Admin API

所有 admin 接口都要求：

- HTTP Basic Auth

v1 约定：

- 用户名来自环境变量 `ADMIN_USERNAME`
- 密码来自环境变量 `ADMIN_PASSWORD`
- admin 能力不依赖普通用户表里的 role 字段

## 9.1 `POST /api/v1/admin/data-versions/activate`

### Request

```json
{
  "data_version": "full-20260412"
}
```

### Response 202

```json
{
  "request_id": "req_600",
  "data": {
    "job_id": "uuid",
    "status": "accepted"
  }
}
```

## 9.2 `POST /api/v1/admin/cache/clear`

### Request

```json
{
  "data_version": "full-20260412",
  "game": "lol"
}
```

## 9.3 `POST /api/v1/admin/jobs/precompute-baselines`

### Request

```json
{
  "data_version": "full-20260412",
  "game": "lol",
  "provider_name": "google",
  "model_name": "gemini-3.1-pro"
}
```

## 9.4 `POST /api/v1/admin/jobs/generate-calibrations`

### Request

```json
{
  "data_version": "full-20260412",
  "games": ["lol", "wild_rift"],
  "models": [
    {
      "provider_name": "google",
      "model_name": "gemini-3.1-pro"
    }
  ]
}
```

## 9.5 `POST /api/v1/admin/jobs/run-benchmarks`

### Request

```json
{
  "dataset_id": "uuid",
  "models": [
    {
      "provider_name": "google",
      "model_name": "gemini-3.1-pro"
    },
    {
      "provider_name": "google",
      "model_name": "gemini-3-flash"
    }
  ]
}
```

## 9.6 `GET /api/v1/admin/jobs/{job_id}`

用途：

- 查询后台 job 状态

## 9.7 `GET /api/v1/admin/metrics`

用途：

- 查询基础运营 metrics snapshot

### Auth

- HTTP Basic Auth

## 10. HTTP 状态码约定

| 场景 | 状态码 |
|---|---|
| 正常读取 | `200` |
| 创建成功 | `201` |
| 流式任务已接受 | `202` |
| 删除成功 | `204` |
| 请求参数错误 | `400` |
| 未登录或 token 无效 | `401` |
| 无权限 | `403` |
| 资源不存在 | `404` |
| 资源冲突 | `409` |
| 语义校验失败 | `422` |
| Provider/上游错误 | `502` |
| 服务器内部错误 | `500` |

## 11. 推荐的错误码集合

建议至少定义这些业务错误码：

- `invalid_input`
- `invalid_provider`
- `invalid_provider_token`
- `invalid_context`
- `invalid_payload`
- `stream_not_supported_for_run_type`
- `unsupported_environment_tag`
- `unsupported_game`
- `session_not_found`
- `unauthorized_session`
- `session_game_mismatch`
- `run_not_found`
- `leaderboard_access_requires_login`
- `provider_error`
- `object_storage_error`
- `admin_only`

## 12. v1 不做的 API 能力

当前明确不做：

- share 链接接口
- public leaderboard
- websocket
- prompt version 管理接口
- 用户自定义环境标签管理

## 13. 落地顺序建议

后端优先做这批接口：

1. `GET /catalog/versions/current`
2. `GET /catalog/{game}/champions|items|runes`
3. `POST /auth/exchange`
4. `GET /me`
5. `POST /sessions`
6. `GET /sessions`
7. `POST /ai/runs`
8. `GET /ai/runs/{run_id}`
9. `GET /ai/runs/{run_id}/events`
10. `GET /leaderboard`

这样就能先跑通主产品路径。
