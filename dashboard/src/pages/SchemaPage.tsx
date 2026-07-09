import { ProTable } from "@ant-design/pro-components";
import { Button, Form, Input, Modal, message } from "antd";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";

export default function SchemaPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["schema-list"],
    queryFn: async () => {
      const r = await api.get("/schema/list");
      return r.data.data as { name: string; version: number; match_method: string }[];
    },
  });

  return (
    <>
      <ProTable
        loading={isLoading}
        rowKey="name"
        search={false}
        dataSource={data || []}
        toolBarRender={() => [
          <Button key="c" type="primary" onClick={() => setOpen(true)}>
            新建 Schema
          </Button>,
        ]}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "版本", dataIndex: "version" },
          { title: "写入策略", dataIndex: "match_method" },
          {
            title: "操作",
            render: (_, row) => (
              <Button
                danger
                size="small"
                onClick={async () => {
                  await api.post("/schema/delete", null, { params: { name: row.name } });
                  message.success("已删除");
                  qc.invalidateQueries({ queryKey: ["schema-list"] });
                }}
              >
                删除
              </Button>
            ),
          },
        ]}
      />
      <Modal title="新建记忆 Schema" open={open} onCancel={() => setOpen(false)} footer={null}>
        <Form
          layout="vertical"
          onFinish={async (v) => {
            await api.post("/schema/create", {
              name: v.name,
              description: v.description,
              match_method: v.match_method || "OVERWRITE",
              storage_type: "KV",
            });
            message.success("已创建");
            setOpen(false);
            qc.invalidateQueries({ queryKey: ["schema-list"] });
          }}
        >
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          <Form.Item name="match_method" label="match_method" initialValue="OVERWRITE">
            <Input />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            创建
          </Button>
        </Form>
      </Modal>
    </>
  );
}
