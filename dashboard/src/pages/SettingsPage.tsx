import { CopyOutlined, KeyOutlined, TeamOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { applyCredentials, getAdminSecret, setAdminSecret } from "../lib/credentials";
import {
  applyApiKey,
  createApiKey,
  createTenant,
  fetchOnboardingProfile,
  listApiKeys,
  type ApiKeyIssue,
} from "../lib/onboarding";
import { api, refreshApiClient } from "../lib/api";
import { apiBaseURL } from "../lib/runtime-config";

function ApiKeyRevealModal({
  issue,
  open,
  onClose,
}: {
  issue: ApiKeyIssue | null;
  open: boolean;
  onClose: () => void;
}) {
  if (!issue) return null;
  return (
    <Modal
      open={open}
      title="API Key 已生成（仅显示一次）"
      onCancel={onClose}
      footer={[
        <Button
          key="copy"
          icon={<CopyOutlined />}
          onClick={async () => {
            await navigator.clipboard.writeText(issue.api_key);
            message.success("已复制到剪贴板");
          }}
        >
          复制 Key
        </Button>,
        <Button
          key="save"
          type="primary"
          onClick={() => {
            applyCredentials(String(issue.tenant_id), String(issue.org_id), issue.api_key);
            message.success("已写入连接设置并生效");
            onClose();
          }}
        >
          保存并用于连接
        </Button>,
      ]}
    >
      <Alert
        type="warning"
        showIcon
        message="请立即保存"
        description="关闭后将无法再次查看完整 Key，只能看到前缀。"
        style={{ marginBottom: 16 }}
      />
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="Tenant ID">{issue.tenant_id}</Descriptions.Item>
        <Descriptions.Item label="Org ID">{issue.org_id}</Descriptions.Item>
        <Descriptions.Item label="User ID">{issue.user_id}</Descriptions.Item>
        <Descriptions.Item label="Key 前缀">{issue.key_prefix}</Descriptions.Item>
        <Descriptions.Item label="API Key">
          <Typography.Text code copyable>
            {issue.api_key}
          </Typography.Text>
        </Descriptions.Item>
      </Descriptions>
    </Modal>
  );
}

function ApplyApiKeyTab() {
  const { user, supabaseEnabled } = useAuth();
  const qc = useQueryClient();
  const [issued, setIssued] = useState<ApiKeyIssue | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const profileQuery = useQuery({
    queryKey: ["onboarding-profile"],
    queryFn: fetchOnboardingProfile,
    enabled: supabaseEnabled && !!user && !!localStorage.getItem("MOS_SUPABASE_USER_ID"),
    retry: false,
  });

  const keysQuery = useQuery({
    queryKey: ["onboarding-api-keys"],
    queryFn: listApiKeys,
    enabled: !!localStorage.getItem("MOS_API_KEY"),
    retry: false,
  });

  const applyMutation = useMutation({
    mutationFn: applyApiKey,
    onSuccess: (data) => {
      setIssued(data);
      setModalOpen(true);
      qc.invalidateQueries({ queryKey: ["onboarding-profile"] });
      qc.invalidateQueries({ queryKey: ["onboarding-api-keys"] });
    },
    onError: (e: unknown) => {
      const msg =
        axiosMessage(e) || (e instanceof Error ? e.message : "申请失败");
      message.error(msg);
    },
  });

  const createKeyMutation = useMutation({
    mutationFn: (name: string) => createApiKey(name),
    onSuccess: (data) => {
      setIssued(data);
      setModalOpen(true);
      keysQuery.refetch();
    },
    onError: (e: unknown) => message.error(axiosMessage(e) || "创建失败"),
  });

  if (supabaseEnabled && !user) {
    return (
      <Alert
        type="info"
        message="请先使用 Supabase 登录"
        description="申请 API Key 需要关联您的 Supabase 账号，请前往 /login。"
      />
    );
  }

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      {profileQuery.data && (
        <Card size="small" title="当前 MemoryEngine 账号">
          <Descriptions column={2} size="small">
            <Descriptions.Item label="Tenant ID">{profileQuery.data.tenant_id}</Descriptions.Item>
            <Descriptions.Item label="Org ID">{profileQuery.data.org_id}</Descriptions.Item>
            <Descriptions.Item label="租户">{profileQuery.data.tenant_code}</Descriptions.Item>
            <Descriptions.Item label="组织">{profileQuery.data.org_code}</Descriptions.Item>
            <Descriptions.Item label="邮箱" span={2}>
              {profileQuery.data.email}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {profileQuery.isError && (
        <Alert
          type="info"
          message="尚未开通 MemoryEngine"
          description="填写下方信息申请 API Key，系统将自动创建个人工作区（租户）。"
        />
      )}

      <Card size="small" title="申请 / 续签 API Key">
        <Form
          layout="vertical"
          initialValues={{
            email: user?.email ?? "",
            display_name: user?.user_metadata?.full_name ?? user?.email ?? "",
            name: "dashboard",
          }}
          onFinish={(v) =>
            applyMutation.mutate({
              email: v.email,
              display_name: v.display_name,
              name: v.name,
            })
          }
        >
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email" }]}>
            <Input disabled={!!user?.email} />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input />
          </Form.Item>
          <Form.Item name="name" label="Key 名称">
            <Input placeholder="dashboard" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={applyMutation.isPending} icon={<KeyOutlined />}>
            申请 API Key
          </Button>
        </Form>
      </Card>

      {localStorage.getItem("MOS_API_KEY") && (
        <Card
          size="small"
          title="已配置的 Key 列表"
          extra={
            <Button size="small" onClick={() => createKeyMutation.mutate("dashboard-extra")}>
              新建 Key
            </Button>
          }
        >
          <Table
            size="small"
            rowKey="id"
            loading={keysQuery.isLoading}
            dataSource={keysQuery.data ?? profileQuery.data?.api_keys ?? []}
            pagination={false}
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "前缀", dataIndex: "key_prefix" },
              {
                title: "状态",
                render: (_, row) =>
                  row.revoked_at ? <Tag color="red">已吊销</Tag> : <Tag color="green">有效</Tag>,
              },
            ]}
          />
        </Card>
      )}

      <ApiKeyRevealModal issue={issued} open={modalOpen} onClose={() => setModalOpen(false)} />
    </Space>
  );
}

function CreateTenantTab() {
  const { user } = useAuth();
  const [issued, setIssued] = useState<ApiKeyIssue | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [adminSecret, setAdminSecretLocal] = useState(getAdminSecret());

  const mutation = useMutation({
    mutationFn: (values: Record<string, string>) =>
      createTenant(
        {
          tenant_code: values.tenant_code,
          tenant_name: values.tenant_name,
          org_code: values.org_code,
          org_name: values.org_name,
          email: values.email,
          display_name: values.display_name,
          api_key_name: values.api_key_name || "default",
          supabase_user_id: user?.id,
        },
        adminSecret,
      ),
    onSuccess: (data) => {
      setIssued(data);
      setModalOpen(true);
      message.success("租户创建成功");
    },
    onError: (e: unknown) => message.error(axiosMessage(e) || "创建失败"),
  });

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Alert
        type="info"
        showIcon
        message="平台管理员"
        description="创建新租户需填写与集群一致的 ADMIN_BOOTSTRAP_SECRET。密钥仅保存在当前浏览器会话（sessionStorage），不会上传。"
      />
      <Form
        layout="vertical"
        initialValues={{
          org_code: "default",
          org_name: "Default Organization",
          api_key_name: "default",
          email: user?.email ?? "",
          display_name: user?.email ?? "",
        }}
        onFinish={(v) => mutation.mutate(v)}
      >
        <Form.Item label="Admin Secret" required>
          <Input.Password
            value={adminSecret}
            onChange={(e) => {
              setAdminSecretLocal(e.target.value);
              setAdminSecret(e.target.value);
            }}
            placeholder="与后端 ADMIN_BOOTSTRAP_SECRET 一致"
          />
        </Form.Item>
        <Form.Item name="tenant_code" label="租户编码" rules={[{ required: true }]}>
          <Input placeholder="acme" />
        </Form.Item>
        <Form.Item name="tenant_name" label="租户名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="org_code" label="组织编码" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="org_name" label="组织名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="email" label="管理员邮箱" rules={[{ required: true, type: "email" }]}>
          <Input />
        </Form.Item>
        <Form.Item name="display_name" label="显示名">
          <Input />
        </Form.Item>
        <Form.Item name="api_key_name" label="API Key 名称">
          <Input />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={mutation.isPending} icon={<TeamOutlined />}>
          创建租户并生成 API Key
        </Button>
      </Form>
      <ApiKeyRevealModal issue={issued} open={modalOpen} onClose={() => setModalOpen(false)} />
    </Space>
  );
}

function ConnectionTab() {
  const { user, supabaseEnabled } = useAuth();

  return (
    <Form
      layout="vertical"
      initialValues={{
        apiBase: apiBaseURL(),
        tenantId: localStorage.getItem("MOS_TENANT_ID") || "1",
        orgId: localStorage.getItem("MOS_ORG_ID") || "1",
        apiKey: localStorage.getItem("MOS_API_KEY") || "",
      }}
      onFinish={(v) => {
        applyCredentials(v.tenantId, v.orgId, v.apiKey || "");
        Object.assign(api.defaults.headers.common, {
          "X-Tenant-Id": v.tenantId,
          "X-Org-Id": v.orgId,
          Authorization: v.apiKey ? `Bearer ${v.apiKey}` : undefined,
        });
        refreshApiClient();
        message.success("已保存");
      }}
    >
      {supabaseEnabled && (
        <Typography.Paragraph>
          Supabase：
          {user ? <Tag color="green">{user.email}</Tag> : <Tag>未登录</Tag>}
        </Typography.Paragraph>
      )}
      <Form.Item name="apiBase" label="API Base（构建时注入，只读）">
        <Input disabled />
      </Form.Item>
      <Form.Item name="tenantId" label="Tenant ID" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item name="orgId" label="Org ID" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item name="apiKey" label="API Key (Bearer)">
        <Input.Password placeholder="在「申请 API Key」页生成后可自动填入" />
      </Form.Item>
      <Button type="primary" htmlType="submit">
        保存连接
      </Button>
    </Form>
  );
}

function axiosMessage(e: unknown): string | undefined {
  if (e && typeof e === "object" && "response" in e) {
    const data = (e as { response?: { data?: { message?: string; detail?: unknown } } }).response?.data;
    if (data?.message) return data.message;
    if (typeof data?.detail === "string") return data.detail;
  }
  return undefined;
}

export default function SettingsPage() {
  return (
    <Card title="设置">
      <Tabs
        items={[
          { key: "connection", label: "连接设置", children: <ConnectionTab /> },
          { key: "apply", label: "申请 API Key", children: <ApplyApiKeyTab /> },
          { key: "tenant", label: "创建租户", children: <CreateTenantTab /> },
        ]}
      />
    </Card>
  );
}
