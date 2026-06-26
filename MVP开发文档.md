# 内部打印服务 MVP 开发文档

## 1. 文档目标

本开发文档用于指导第一阶段（MVP）编码实现，目标是**在公司内网完成 PDF 自助打印闭环**，并确保后续可扩展到钉钉免登、权限控制、多格式打印。

---

## 2. MVP 范围定义

### 2.1 包含范围

1. Web 页面上传 PDF。
2. 获取可用打印机列表并选择目标打印机。
3. 创建打印任务并入队。
4. 后台单工作线程消费队列并调用 SumatraPDF 打印。
5. SQLite 持久化任务状态与错误信息。
6. 查询任务列表与任务详情状态。
7. 定时清理临时文件。
8. 健康检查接口。

### 2.2 不包含范围

1. Word/Excel/图片直接打印。
2. 钉钉免登与部门权限。
3. 打印审批、计费、报表后台。
4. 多打印机调度策略（仅支持手工选择打印机）。

---

## 3. 技术栈与运行环境

1. Python 3.10+
2. uv（Python 环境与依赖管理）
3. Flask（Web）
4. Waitress（生产启动）
5. SQLite（任务存储）
6. pywin32（读取 Windows 打印机）
7. SumatraPDF（命令行静默打印）

### 3.1 uv 规范（统一执行）

MVP 开发统一使用 `uv` 管理虚拟环境与依赖，不再使用 `pip + requirements.txt` 作为主流程。

推荐命令：

```bash
uv init
uv add flask waitress pywin32
uv sync
uv run python app.py
```

生产启动示例：

```bash
uv run waitress-serve --host=0.0.0.0 --port=5000 app:app
```

---

## 4. 系统架构（MVP）

```text
前端上传页
   ↓ HTTP
Flask API
   ├─ 文件校验与落盘
   ├─ SQLite 任务表
   └─ Queue 任务队列
        ↓
   打印Worker线程
        ↓
SumatraPDF 命令行
        ↓
Windows Print Spooler
        ↓
物理打印机
```

---

## 5. 目录结构（建议）

```text
print-service/
├── app.py
├── config.py
├── pyproject.toml
├── uv.lock
├── data/
│   └── print_service.db
├── uploads/
├── logs/
│   └── app.log
├── templates/
│   └── upload.html
├── static/
│   └── app.css
├── services/
│   ├── printer_service.py
│   ├── job_service.py
│   ├── file_service.py
│   └── cleanup_service.py
├── workers/
│   └── print_worker.py
├── repositories/
│   └── job_repository.py
└── tools/
    └── SumatraPDF.exe
```

---

## 6. 配置项设计（config.py）

| 配置项                        | 类型      | 默认值                   | 说明                         |
| ----------------------------- | --------- | ------------------------ | ---------------------------- |
| HOST                          | str       | `0.0.0.0`                | 监听地址                     |
| PORT                          | int       | `5000`                   | 服务端口                     |
| DB_PATH                       | str       | `data\\print_service.db` | SQLite 文件                  |
| DB_JOURNAL_MODE               | str       | `WAL`                    | SQLite 日志模式              |
| DB_BUSY_TIMEOUT_MS            | int       | `5000`                   | SQLite 锁等待超时            |
| UPLOAD_DIR                    | str       | `uploads`                | 上传根目录                   |
| LOG_PATH                      | str       | `logs\\app.log`          | 日志文件                     |
| MAX_FILE_SIZE_MB              | int       | `50`                     | 单文件大小上限               |
| ALLOWED_EXTENSIONS            | list[str] | `[".pdf"]`               | 允许格式                     |
| CLEANUP_SUCCESS_AFTER_MINUTES | int       | `10`                     | 成功任务文件删除时间         |
| CLEANUP_FAILED_AFTER_HOURS    | int       | `24`                     | 失败任务文件保留时长         |
| CLEANUP_INTERVAL_MINUTES      | int       | `10`                     | 清理任务执行周期             |
| SUMATRA_PATH                  | str       | `tools\\SumatraPDF.exe`  | Sumatra 可执行文件           |
| PRINT_COMMAND_TIMEOUT_SEC     | int       | `120`                    | 打印命令超时                 |
| STARTUP_RECOVER_PRINTING_MODE | str       | `fail`                   | 启动时 `printing` 任务处理策略 |

---

## 7. 数据模型设计（SQLite）

### 7.1 表结构：print_jobs

```sql
CREATE TABLE IF NOT EXISTS print_jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  user_name TEXT,
  source_filename TEXT NOT NULL,
  stored_filepath TEXT NOT NULL,
  file_size_bytes INTEGER NOT NULL,
  printer_name TEXT NOT NULL,
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  cleaned_at TEXT
);
```

### 7.2 索引

```sql
CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status);
CREATE INDEX IF NOT EXISTS idx_print_jobs_created_at ON print_jobs(created_at);
```

### 7.3 状态机

`pending -> printing -> submitted -> success`

`pending/printing/submitted -> failed`

`success/failed -> deleted`（仅表示文件已清理，保留任务记录）

---

## 8. API 设计（MVP）

### 8.0 响应结构约定（统一）

除下载类接口外，统一返回：

```json
{
  "code": "OK",
  "message": "success",
  "data": {}
}
```

### 8.1 获取打印机列表

- **Method**: `GET /api/printers`
- **Response 200**

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "items": [
      { "name": "HP LaserJet P1108" },
      { "name": "Microsoft Print to PDF" }
    ]
  }
}
```

### 8.2 创建打印任务

- **Method**: `POST /api/print-jobs`
- **Content-Type**: `multipart/form-data`
- **Form 字段**
  - `file`: PDF 文件
  - `printer_name`: 打印机名称
  - `user_name`（可选，MVP 可由页面输入）
- **Response 201**

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "id": "job_20260617_102530_ab12cd",
    "status": "pending",
    "created_at": "2026-06-17T10:25:30+08:00"
  }
}
```

### 8.3 查询任务详情

- **Method**: `GET /api/print-jobs/{id}`
- **Response 200**

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "id": "job_20260617_102530_ab12cd",
    "source_filename": "合同.pdf",
    "printer_name": "HP LaserJet P1108",
    "status": "submitted",
    "delivery_level": "submitted_to_spooler",
    "error_message": null,
    "created_at": "2026-06-17T10:25:30+08:00",
    "started_at": "2026-06-17T10:25:31+08:00",
    "finished_at": "2026-06-17T10:25:33+08:00"
  }
}
```

### 8.4 查询任务列表

- **Method**: `GET /api/print-jobs?status=pending&page=1&page_size=50&order_by=created_at&order=desc`
- **Response 200**

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "items": [],
    "total": 0,
    "page": 1,
    "page_size": 50
  }
}
```

### 8.5 健康检查

- **Method**: `GET /health`
- **Response 200**

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "status": "ok",
    "printer_count": 1,
    "queue_size": 0,
    "worker_alive": true,
    "db_writable": true,
    "sumatra_exists": true
  }
}
```

---

## 9. 核心流程与实现约束

### 9.1 上传与入队流程

1. 校验 `printer_name` 非空且存在于系统打印机列表。
2. 校验文件扩展名 `.pdf`、MIME（`application/pdf`）与文件头魔数（`%PDF-`）。
3. 校验大小不超过配置上限。
4. 生成任务 ID 与服务端唯一文件名。
5. 按日期创建目录 `uploads\\YYYY-MM-DD\\` 并保存文件。
6. 写入 `print_jobs`（status=`pending`）。
7. 将任务 ID 放入内存队列。
8. 返回 201。

### 9.2 Worker 打印流程

1. 从队列取任务 ID。
2. 更新状态为 `printing`，记录 `started_at`。
3. 执行命令：

```bash
SumatraPDF.exe -print-to "<printer_name>" -silent "<stored_filepath>"
```

4. 命令退出码为 0：状态更新为 `submitted`，随后标记 `success`（语义：已提交到 Windows 打印链路）。
5. 命令失败/超时：状态更新为 `failed`，写入 `error_message`。
6. 记录 `finished_at`。

> 说明：MVP 的 `success` 表示服务端命令执行成功并提交到系统打印链路，不保证纸张已完成输出。

### 9.3 清理流程

1. 每 `CLEANUP_INTERVAL_MINUTES` 执行一次。
2. `success` 且超过 `CLEANUP_SUCCESS_AFTER_MINUTES` 的文件删除，任务状态改 `deleted`，写 `cleaned_at`。
3. `failed` 且超过 `CLEANUP_FAILED_AFTER_HOURS` 的文件删除，任务状态改 `deleted`，写 `cleaned_at`。
4. 删除磁盘上无 DB 记录且超过 24 小时的孤立旧文件（按日期目录扫描）。
5. 清理前需二次校验任务状态，禁止删除 `pending/printing/submitted` 任务对应文件。

### 9.4 服务启动恢复流程

1. 服务启动完成 DB 初始化后，先扫描 `print_jobs`。
2. `pending` 任务重新入内存队列。
3. `printing` 任务按配置处理：`STARTUP_RECOVER_PRINTING_MODE=fail` 时标记 `failed` 并写入 `error_message=service_restart`；`retry` 时重置为 `pending` 并重新入队。
4. `submitted/success/failed/deleted` 任务不做状态回退。

### 9.5 SQLite 并发与事务约束

1. Flask 请求线程、Worker 线程、清理线程均使用“每线程独立连接”，禁止跨线程复用连接对象。
2. 启动时执行 `PRAGMA journal_mode=WAL;` 与 `PRAGMA busy_timeout=<DB_BUSY_TIMEOUT_MS>;`。
3. 所有状态变更使用显式事务提交，失败时回滚并记录错误日志。
4. 涉及“查询+更新”的步骤按任务 ID 做原子更新，避免重复消费与状态覆盖。

---

## 10. 前端页面（upload.html）最低要求

1. 输入项：用户名称（可选）、打印机下拉框、PDF 文件选择。
2. 按钮：上传并打印。
3. 展示：最近 10 条任务状态（轮询 `/api/print-jobs`）。
4. 错误提示：文件格式错误、文件过大、打印机不存在、服务异常。

---

## 11. 日志与错误码

### 11.1 日志字段

每条关键日志至少包含：

- `job_id`
- `action`（upload/queue/print/cleanup）
- `status`
- `printer_name`
- `message`
- `timestamp`

### 11.2 API 错误码（建议）

| code                | HTTP | 场景         |
| ------------------- | ---- | ------------ |
| `INVALID_FILE_TYPE` | 400  | 非 PDF       |
| `FILE_TOO_LARGE`    | 400  | 文件超限     |
| `PRINTER_NOT_FOUND` | 400  | 打印机不存在 |
| `UPLOAD_FAILED`     | 500  | 文件保存失败 |
| `QUEUE_FAILED`      | 500  | 入队失败     |
| `PRINT_FAILED`      | 500  | 打印命令失败 |
| `JOB_NOT_FOUND`     | 404  | 任务不存在   |

---

## 12. 安全基线（MVP 必做）

1. 服务仅监听内网地址或通过防火墙限制来源网段。
2. 限制可上传文件类型与大小。
3. 文件名重命名，禁止使用原始文件名落盘。
4. 上传目录仅作数据存储，不允许执行权限。
5. 日志中不记录文件内容，只记录元信息。

---

## 13. 开发任务拆分（按编码顺序）

1. 初始化项目结构与依赖。
2. 实现配置加载、日志初始化、数据库初始化。
3. 实现打印机查询服务（pywin32）。
4. 实现文件上传、校验、落盘服务。
5. 实现任务仓储与状态更新逻辑。
6. 实现队列与 Worker。
7. 实现 SumatraPDF 调用封装。
8. 实现 API 与上传页面。
9. 实现定时清理任务。
10. 实现健康检查与基础运维信息输出。

第 1 步需按 uv 执行：

```bash
uv init
uv add flask waitress pywin32
uv sync
```

---

## 14. MVP 验收标准（开发完成判定）

1. 内网用户可访问上传页面并提交 PDF。
2. 可获取打印机列表且可选定打印机。
3. 打印任务可入队并被 Worker 消费。
4. 数据库可完整记录任务生命周期。
5. 失败场景可返回明确错误信息并写日志。
6. 临时文件可按策略自动清理。
7. 服务重启后可继续处理新任务。
8. 在持续运行 72 小时内无阻断性故障。

---

## 15. 与后续迭代的兼容约束

为减少重构，MVP 开发时需保留以下扩展点：

1. `user_id/user_name` 字段保留，为钉钉免登做准备。
2. `print_jobs` 状态机不要写死在页面层，统一在服务层维护。
3. 文件处理流程抽象为独立服务，后续可插入“Office 转 PDF”流程。
4. API 返回结构固定为 `code/message/data`，后续版本保持兼容扩展。
