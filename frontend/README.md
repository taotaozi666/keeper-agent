<!--
  前端项目说明文档
  记录启动方式、代理配置和部署时的环境变量
-->

# Shopkeeper Agent Frontend

匹配后端 `shopkeeper-agent` 的问数聊天前端，技术栈为 React + Vite + Tailwind CSS + pnpm。

## 启动

```bash
cd frontend
pnpm install
pnpm dev
```

默认开发代理会把 `/api` 转发到 `http://127.0.0.1:8000`，对应后端的 `POST /api/query` SSE 接口。

如需修改后端地址：

```bash
cp .env.example .env
```

然后调整：

```bash
VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000
```

如果前端与后端不在同一域部署，可设置：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## 流式结果与空数据

`result`（包括空数组）和 `error` 是流式响应的终态。收到后结束读取，避免连接关闭异常覆盖最终结果。空数组显示“没有符合条件的数据”；没有收到终态就断流时仍报告失败。

支持 LF / CRLF 换行及跨网络包的 UTF-8 中文。运行回归测试：

```bash
pnpm test
```

测试使用 Node.js 内置测试运行器与 TypeScript 类型剥离，不需要启动后端或调用模型。建议使用 Node.js 22.12+，低版本需升级。

## 流程展示模式

通过 `frontend/.env` 配置（不影响后端工作流）：

```dotenv
# 调试阶段：原有实时拓扑流程图
VITE_PROGRESS_VIEW=graph
```

```dotenv
# 简洁模式：默认折叠的步骤列表
VITE_PROGRESS_VIEW=compact
```

简洁模式运行时只显示最新的进行中步骤，可展开查看所有已发生步骤及状态；完成、失败或中止时自动收起，结果直接展示在下方，之后仍可重新展开。并行节点优先展示仍在执行的步骤，步骤列表按首次出现顺序原位更新。

本地配置及示例模板设为 `compact`。不配置时，Vite 开发模式默认 `graph`，生产构建默认 `compact`。修改环境变量后重启开发服务器；部署构建需重新执行 `pnpm build`，因为 Vite 环境变量在构建时注入。


### 会话恢复

当前会话 ID 保存在 localStorage 的 `keeper.conversation`，刷新时从 `GET /api/conversations/{id}` 恢复记录。新会话清除当前 ID；不删除后端历史。恢复失败时显示错误并暂停发送，可新建会话继续。SSE 的 `conversation` 为非终态，`clarification`、`reply`、`result`、`error` 为终态。历史结果超过存储上限时展示截断说明。

左侧为历史会话列表，按更新时间倒序展示首条问题和时间，支持加载更多、选中高亮和点击恢复。查询过程中禁止切换，结束后自动刷新列表；新会话不会删除旧记录。

开发代理显式使用 HTTP/HTTPS Keep-Alive Agent，并将上游 `Connection` 设为 `keep-alive`，规避本地 Windows 后端关闭连接时偶发的 `ECONNRESET`。此配置仅影响 Vite 开发代理，不设置 SSE 请求超时，也不会自动重发查询。
