# Memory Engine 部署说明

## 统一镜像

API、Dashboard 共用根目录 `Dockerfile`，运行时通过 `MEMORY_ENGINE_ROLE` 选择进程：

| `MEMORY_ENGINE_ROLE` | 进程 |
|-----------------|------|
| `api`（默认） | FastAPI `run_server.sh`，端口 6030 |
| `dashboard` | Nginx 静态前端，端口 80 |

```bash
# 仓库根目录（默认 target=full，含 Dashboard）
docker build -t memory-engine:latest .

# 仅 API（更快，无前端静态资源）
docker build --target api -t memory-engine-api:latest .

# 本地试跑
docker run --rm -e MEMORY_ENGINE_ROLE=api -p 6030:6030 memory-engine:latest
docker run --rm -e MEMORY_ENGINE_ROLE=dashboard -p 8080:80 memory-engine:latest
```

构建参数（可选）：

```text
NPM_REGISTRY=https://registry.npmjs.org
UV_INDEX_URL=https://pypi.org/simple
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
```

可选：使用 `docker/Dockerfile.pydeps` 预构建 Python 依赖层，加速 CI 缓存。

## K8s 单文件部署

`k8s-Deployment.yaml` 内含 **API Deployment + Service + Ingress**、**Dashboard Deployment + Service + Ingress**。

```bash
export NAMESPACE=memory-engine
export IMAGE_URL=registry.example.com/memory-engine:latest
export APP_NAME=memory-engine-api
export REPLICAS=2
export CPU_LIMIT=2 CPU_REQUEST=500m MEMORY_LIMIT=4Gi MEMORY_REQUEST=1Gi
export KAFKA_CONSUMERS_ENABLED=false
export DASHBOARD_APP_NAME=memory-engine-dashboard
export DASHBOARD_REPLICAS=1
export DASHBOARD_CPU_LIMIT=500m DASHBOARD_CPU_REQUEST=100m
export DASHBOARD_MEMORY_LIMIT=512Mi DASHBOARD_MEMORY_REQUEST=128Mi
export API_INGRESS_HOST=api.memory-engine.example.com
export DASHBOARD_INGRESS_HOST=dashboard.memory-engine.example.com
export INGRESS_TLS_SECRET=ingress-tls
# End-user memory APIs: configure token validation via Redis or account service URL
# export USER_TOKEN_REDIS_KEY_TEMPLATE='app:user:token:{user_id}'
# export USER_ACCOUNT_VALIDATE_URL=http://auth-service/internal/validate
# export END_USER_DEFAULT_TENANT_ID=1

envsubst < k8s-Deployment.yaml | kubectl apply -f -
```

## 部署顺序建议

1. MySQL 迁移（`backend/migrations/mysql/`）
2. 基础设施：Redis、Kafka、MongoDB、Qdrant
3. 构建并推送统一镜像 → `envsubst` 应用 `k8s-Deployment.yaml`
4. 通过 `POST /admin/tenants` 或种子 SQL 创建 API Key（见 [docs/user-guide.md](../docs/user-guide.md)）

## 依赖说明

- API Pod 可设 `KAFKA_CONSUMERS_ENABLED=true` 运行 schema/billing Consumer。
- Temporal Worker（`memory-engine-worker`）默认不在 K8s 部署；本地调试见 `backend/README.md`。
- 生产密钥使用 K8s Secret，勿写入 Dockerfile 或镜像层。
