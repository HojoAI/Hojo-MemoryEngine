import type { ActionType, ProColumns } from "@ant-design/pro-components";
import { ProTable } from "@ant-design/pro-components";
import { Alert, Button, Form, Input, Modal, Select, Typography, message } from "antd";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../lib/api";

type MemoryRow = {
  user_id: string;
  memory_field_name: string;
  value: unknown;
};

type MemoryListPage = {
  items: MemoryRow[];
  total: number;
};

type SessionInfo = {
  memory_user_id: string;
  key_prefix: string;
  tenant_id: number;
  org_id: number;
};

export default function MemoryDataPage() {
  const qc = useQueryClient();
  const actionRef = useRef<ActionType>();
  const [open, setOpen] = useState(false);
  const [userIdFilter, setUserIdFilter] = useState("");
  const hasApiKey = Boolean(localStorage.getItem("MOS_API_KEY"));

  const sessionQuery = useQuery({
    queryKey: ["onboarding-session"],
    queryFn: async () => {
      const r = await api.get("/onboarding/session");
      return r.data.data as SessionInfo;
    },
    enabled: hasApiKey,
    retry: false,
  });

  const session = sessionQuery.data;
  const memoryUserId =
    session?.memory_user_id || session?.key_prefix || null;

  const columns: ProColumns<MemoryRow>[] = [
    { title: "用户", dataIndex: "user_id", width: 180, ellipsis: true },
    { title: "记忆字段", dataIndex: "memory_field_name", width: 160 },
    {
      title: "值",
      dataIndex: "value",
      render: (_, r) => JSON.stringify(r.value),
    },
  ];

  const reloadTable = () => {
    actionRef.current?.reloadAndRest?.();
  };

  return (
    <>
      {!hasApiKey && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="未配置 API Key"
          description="请先在「设置 → 连接设置」中保存 API Key，页面将自动加载当前租户下全部用户的记忆数据。"
        />
      )}

      {sessionQuery.isError && hasApiKey && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="无法解析当前 API Key"
          description="请检查连接设置中的 Tenant / Org / API Key 是否正确。"
        />
      )}

      <ProTable<MemoryRow>
        actionRef={actionRef}
        rowKey={(r) => `${r.user_id}-${r.memory_field_name}`}
        search={false}
        columns={columns}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        toolBarRender={() => [
          <Input.Search
            key="user-filter"
            placeholder="搜索用户 ID（部分匹配）"
            allowClear
            style={{ width: 240 }}
            value={userIdFilter}
            disabled={!hasApiKey}
            onChange={(e) => setUserIdFilter(e.target.value)}
            onSearch={reloadTable}
            onClear={() => {
              setUserIdFilter("");
              setTimeout(reloadTable, 0);
            }}
          />,
          session ? (
            <Typography.Text key="scope" type="secondary">
              租户 {session.tenant_id} / 组织 {session.org_id}
              {memoryUserId ? ` · 写入分区：${memoryUserId}` : ""}
            </Typography.Text>
          ) : null,
          <Button
            key="r"
            onClick={() => actionRef.current?.reload()}
            disabled={!hasApiKey}
          >
            刷新
          </Button>,
          <Button
            key="a"
            type="primary"
            onClick={() => setOpen(true)}
            disabled={!memoryUserId}
          >
            写入记忆
          </Button>,
        ]}
        request={async (params) => {
          if (!hasApiKey) {
            return { data: [], success: true, total: 0 };
          }
          const current = params.current ?? 1;
          const pageSize = params.pageSize ?? 10;
          const trimmedUserId = userIdFilter.trim();
          try {
            const r = await api.get("/data/list", {
              params: {
                scope: "tenant",
                offset: (current - 1) * pageSize,
                limit: pageSize,
                ...(trimmedUserId ? { user_id: trimmedUserId } : {}),
              },
            });
            const page = r.data.data as MemoryListPage;
            return {
              data: page.items ?? [],
              success: true,
              total: page.total ?? 0,
            };
          } catch {
            return { data: [], success: false, total: 0 };
          }
        }}
      />

      <Modal
        title="写入记忆 (LLM parse)"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
      >
        <Form
          layout="vertical"
          onFinish={async (v) => {
            if (!memoryUserId) {
              message.error("无法确定当前用户分区");
              return;
            }
            await api.post("/data/create", {
              user_id: memoryUserId,
              memory_field_name: v.field,
              query: v.query,
              parse_rule_name: v.parseRule || undefined,
              write_rule: v.writeRule || "OVERWRITE",
            });
            message.success("已写入");
            setOpen(false);
            qc.invalidateQueries({ queryKey: ["data-list"] });
            actionRef.current?.reload();
          }}
        >
          <Form.Item name="field" label="memory_field_name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="query" label="原始文本 query" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="parseRule" label="parse_rule_name">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="writeRule" label="write_rule" initialValue="OVERWRITE">
            <Select
              options={["OVERWRITE", "APPEND", "MERGE"].map((x) => ({
                value: x,
                label: x,
              }))}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            提交
          </Button>
        </Form>
      </Modal>
    </>
  );
}
