import { useQuery } from "@tanstack/react-query";
import { ProTable } from "@ant-design/pro-components";
import { Tabs } from "antd";
import { api } from "../lib/api";

export default function RulesPage() {
  const parseQ = useQuery({
    queryKey: ["parse-rules"],
    queryFn: async () => (await api.get("/schema/parse/list")).data.data,
  });
  const retrieveQ = useQuery({
    queryKey: ["retrieve-rules"],
    queryFn: async () => (await api.get("/schema/retrieve/list")).data.data,
  });
  const callQ = useQuery({
    queryKey: ["call-rules"],
    queryFn: async () => (await api.get("/schema/call/list")).data.data,
  });

  const cols = [
    { title: "记忆字段", dataIndex: "memory_field_name" },
    { title: "规则名", dataIndex: "rule_name" },
    { title: "版本", dataIndex: "version" },
  ];

  return (
    <Tabs
      items={[
        {
          key: "parse",
          label: "解析规则",
          children: (
            <ProTable
              rowKey="id"
              search={false}
              loading={parseQ.isLoading}
              dataSource={parseQ.data || []}
              columns={cols}
            />
          ),
        },
        {
          key: "retrieve",
          label: "检索规则",
          children: (
            <ProTable
              rowKey="id"
              search={false}
              loading={retrieveQ.isLoading}
              dataSource={retrieveQ.data || []}
              columns={[...cols, { title: "方法", dataIndex: "retrieve_method" }]}
            />
          ),
        },
        {
          key: "call",
          label: "引用规则",
          children: (
            <ProTable
              rowKey="id"
              search={false}
              loading={callQ.isLoading}
              dataSource={callQ.data || []}
              columns={[...cols, { title: "槽位", dataIndex: "slot_name" }]}
            />
          ),
        },
      ]}
    />
  );
}
