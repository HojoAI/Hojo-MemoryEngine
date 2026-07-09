import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ProTable } from "@ant-design/pro-components";
import { Button, message, Space } from "antd";
import { api } from "../lib/api";

type Proposal = {
  proposal_uuid: string;
  status: string;
  confidence_score?: number;
  risk_level?: string;
  target_type?: string;
  action?: string;
};

export default function GovernancePage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["proposals"],
    queryFn: async () => (await api.get("/governance/proposals")).data.data as Proposal[],
  });

  return (
    <ProTable
      loading={isLoading}
      rowKey="proposal_uuid"
      search={false}
      dataSource={data || []}
      columns={[
        { title: "提案 UUID", dataIndex: "proposal_uuid", ellipsis: true },
        { title: "状态", dataIndex: "status" },
        { title: "置信度", dataIndex: "confidence_score" },
        { title: "风险", dataIndex: "risk_level" },
        { title: "目标", dataIndex: "target_type" },
        { title: "动作", dataIndex: "action" },
        {
          title: "操作",
          render: (_, row) => (
            <Space>
              <Button
                size="small"
                disabled={row.status !== "pending_review"}
                onClick={async () => {
                  await api.post(`/governance/proposals/${row.proposal_uuid}/approve`);
                  message.success("已批准");
                  qc.invalidateQueries({ queryKey: ["proposals"] });
                }}
              >
                批准
              </Button>
              <Button
                size="small"
                type="primary"
                disabled={!["approved", "pending_review"].includes(row.status)}
                onClick={async () => {
                  await api.post(`/governance/proposals/${row.proposal_uuid}/apply`);
                  message.success("已应用");
                  qc.invalidateQueries({ queryKey: ["proposals"] });
                }}
              >
                应用
              </Button>
            </Space>
          ),
        },
      ]}
    />
  );
}
