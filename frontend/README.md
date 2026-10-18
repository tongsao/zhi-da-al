# 智答 · 前端

Vue 3 + Vite + Element Plus + Pinia + Axios 的最小完整前端，覆盖需求文档中的 11 个接口。

## 启动

```bash
cd frontend
npm install
npm run dev
```

默认启动在 http://localhost:5173，已通过 Vite proxy 把 `/api` 转发到 `http://localhost:8000`（即 FastAPI 后端）。

## 页面

| 路由 | 功能 | 主要接口 |
|---|---|---|
| `/qa` | 智能问答（多轮对话 + 反馈） | POST /qa/chat, POST /qa/feedback |
| `/documents` | 知识库管理（上传/列表/删除/详情） | /documents 系列 |
| `/kb` | 知识库维护（统计 + 重建） | /kb/stats, /kb/rebuild |
| `/eval` | 效果评测 | POST /eval/run |

## 目录结构

```
frontend/
├── package.json
├── vite.config.js
├── index.html
└── src/
    ├── main.js
    ├── App.vue              # 左侧菜单 + 顶部健康状态
    ├── api/index.js         # axios 封装，统一拦截后端响应结构
    ├── router/index.js
    ├── stores/chat.js       # Pinia 会话状态
    └── views/
        ├── QaView.vue
        ├── DocumentsView.vue
        ├── KbView.vue
        └── EvalView.vue
```

## 后端约定

- 所有接口前缀 `/api/v1`
- 统一响应：`{ code, message, data }`，`code===0` 视为成功
- 错误由 `api/index.js` 拦截器统一弹 `ElMessage.error`

## 生产构建

```bash
npm run build   # 输出到 dist/
```

将 `dist/` 用 Nginx 部署时，记得把 `/api/` 反向代理到 FastAPI。