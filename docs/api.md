# LearnHub API 接口文档（当前已实现）

本文档基于 `services/api/main.py` 和 `shared/schemas.py` 中已实现的接口整理，提供给前端对接使用。

## 通用说明

### Base URL

- 本地默认：`http://localhost:8000`

### 认证

- 除了健康检查与已废弃的旧认证接口外，所有接口均需要 `Authorization: Bearer <token>`。
- 认证失败将返回统一响应结构，`code` 为 HTTP 状态码（如 401/403）。

### 通用响应结构

所有接口统一返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "request_id": "..."
}
```

- `code`：0 表示成功；否则为 HTTP 状态码。
- `message`：成功为 `ok`，失败为错误描述。
- `data`：业务数据。
- `request_id`：服务端生成的请求 ID。

### 统一错误

- 404：资源不存在（`message` 为 `not found` 或具体描述）。
- 409：版本冲突（Problem 更新时 `version` 不一致）。
- 410：旧认证接口已废弃（`message` 为 `Auth handled by Better Auth; use /api/auth`）。
- 400：参数校验错误（`message` 为 `validation_error`，`data.errors` 为详细字段错误）。

---

## 健康检查

### GET `/healthz`

- Auth：否
- 响应 `data`：`"ok"`

---

## 旧认证接口（已废弃，仅保留占位）

> 所有接口返回 `code: 410`，`message: Auth handled by Better Auth; use /api/auth`。

### POST `/api/v1/auth/sms/send`

**请求体**

```json
{
  "phone": "string"
}
```

### POST `/api/v1/auth/sms/verify`

**请求体**

```json
{
  "phone": "string",
  "code": "string"
}
```

### POST `/api/v1/auth/refresh`

**请求体**

```json
{
  "refresh_token": "string"
}
```

### POST `/api/v1/auth/logout`

**请求体**

```json
{
  "refresh_token": "string"
}
```

### GET `/api/v1/auth/wechat/web/authorize`

### GET `/api/v1/auth/wechat/web/callback`

**Query 参数**

- `code`: string
- `state`: string

### POST `/api/v1/auth/exchange`

**请求体**

```json
{
  "one_time_code": "string"
}
```

---

## 用户

### GET `/api/v1/me`

- Auth：是

**响应 data**

```json
{
  "id": "uuid",
  "nickname": "string",
  "avatar_url": "string | null",
  "email": "string | null"
}
```

---

## 题单（Collections）

### POST `/api/v1/collections`

- Auth：是

**请求体**

```json
{
  "name": "string"
}
```

**响应 data**

```json
{
  "id": "uuid",
  "name": "string"
}
```

### GET `/api/v1/collections`

- Auth：是

**响应 data**

```json
[
  {
    "id": "uuid",
    "name": "string",
    "problem_count": 0
  }
]
```

### GET `/api/v1/collections/{collection_id}`

- Auth：是

**响应 data**

```json
{
  "id": "uuid",
  "name": "string"
}
```

### PATCH `/api/v1/collections/{collection_id}`

- Auth：是

**请求体**

```json
{
  "name": "string | null"
}
```

**响应 data**

```json
{
  "id": "uuid",
  "name": "string"
}
```

### DELETE `/api/v1/collections/{collection_id}`

- Auth：是

**响应 data**

```json
{
  "deleted": true
}
```

---

## 题目（Problems）

### POST `/api/v1/problems`

- Auth：是

**请求体**

```json
{
  "collection_id": "uuid",
  "original_image_url": "string",
  "cropped_image_url": "string | null",
  "order_index": 0
}
```

**响应 data**

```json
{
  "id": "uuid",
  "status": "DRAFT"
}
```

### GET `/api/v1/collections/{collection_id}/problems`

- Auth：是

**Query 参数**

- `limit`: int (1-100, default 20)
- `offset`: int (>=0, default 0)
- `updated_after`: string (ISO datetime, 可选)

**响应 data**

```json
[
  {
    "id": "uuid",
    "status": "string",
    "original_image_url": "string",
    "cropped_image_url": "string | null",
    "ocr_text": "string | null",
    "note": "string | null",
    "tags": "any | null",
    "order_index": 0,
    "version": 0
  }
]
```

### GET `/api/v1/problems/{problem_id}`

- Auth：是

**响应 data**

```json
{
  "id": "uuid",
  "status": "string",
  "original_image_url": "string",
  "cropped_image_url": "string | null",
  "ocr_text": "string | null",
  "note": "string | null",
  "tags": "any | null",
  "order_index": 0,
  "version": 0
}
```

### PATCH `/api/v1/problems/{problem_id}`

- Auth：是
- 备注：必须传 `version`，服务端对比不一致返回 409。

**请求体**

```json
{
  "ocr_text": "string | null",
  "note": "string | null",
  "tags": "any | null",
  "order_index": 0,
  "collection_id": "uuid | null",
  "version": 0
}
```

**响应 data**

```json
{
  "id": "uuid",
  "version": 1
}
```

### DELETE `/api/v1/problems/{problem_id}`

- Auth：是

**响应 data**

```json
{
  "deleted": true
}
```

---

## 文件上传（Uploads）

### POST `/api/v1/uploads/presign`

- Auth：是

**请求体**

```json
{
  "filename": "string",
  "content_type": "string",
  "size": 0
}
```

**响应 data**

> 实际字段由 `build_presign_response` 返回，通常包含 `object_key`、`url`、`headers` 等。

### POST `/api/v1/uploads/direct`

- Auth：是
- Content-Type: `multipart/form-data`

**Query 参数**

- `object_key`: string（必须以 `user/{user_id}/` 开头）

**表单字段**

- `file`: 上传文件

**响应 data**

```json
{
  "object_key": "string",
  "url": "string"
}
```

### POST `/api/v1/uploads/complete`

- Auth：是

**请求体**

```json
{
  "object_key": "string"
}
```

**响应 data**

```json
{
  "url": "string"
}
```

---

## OCR

### POST `/api/v1/problems/{problem_id}/ocr`

- Auth：是

**请求体**

```json
{
  "image_url": "string | null",
  "idempotency_key": "string | null"
}
```

**响应 data**

```json
{
  "job_id": "uuid"
}
```

---

## 任务（Jobs）

### GET `/api/v1/jobs/{job_id}`

- Auth：是

**响应 data**

```json
{
  "status": "string",
  "result": "any | null",
  "error_message": "string | null"
}
```

---

## PDF 导出

### POST `/api/v1/collections/{collection_id}/export_pdf`

- Auth：是

**请求体**

```json
{
  "idempotency_key": "string | null",
  "options": "any | null"
}
```

**响应 data**

```json
{
  "job_id": "uuid"
}
```
