# APISIX Gateway (Memory Engine)

## 启动

```bash
cd infra/docker-compose
docker compose up -d etcd apisix redis kafka
```

API 在宿主机 `6030` 时，网关入口：

- `http://127.0.0.1:9080/api/v1/...`
- `http://127.0.0.1:9080/health`

Dashboard `.env`:

```bash
VITE_APISIX_URL=http://127.0.0.1:9080
```

## 路由

见 `apisix.yaml`：将 `/api/*` 反代到 `host.docker.internal:6030`。

生产可启用 `key-auth` 插件，与 MySQL `api_key` 前缀校验配合（FastAPI 仍做权限细粒度校验）。
