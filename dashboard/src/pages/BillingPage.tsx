import { ProTable } from "@ant-design/pro-components";
import { Card, Col, Row, Statistic, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

export default function BillingPage() {
  const summaryQ = useQuery({
    queryKey: ["billing-summary"],
    queryFn: async () => (await api.get("/billing/summary")).data.data,
  });
  const eventsQ = useQuery({
    queryKey: ["billing-events"],
    queryFn: async () => (await api.get("/billing/events", { params: { limit: 50 } })).data.data,
  });
  const invoicesQ = useQuery({
    queryKey: ["billing-invoices"],
    queryFn: async () => (await api.get("/billing/invoices")).data.data,
  });

  const summary = summaryQ.data as {
    total_tokens?: number;
    total_cost?: number;
    event_count?: number;
  };

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="近30日 Tokens" loading={summaryQ.isLoading} value={summary?.total_tokens ?? 0} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="近30日费用 (CNY)" loading={summaryQ.isLoading} value={summary?.total_cost ?? 0} precision={4} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="事件数" loading={summaryQ.isLoading} value={summary?.event_count ?? 0} />
          </Card>
        </Col>
      </Row>
      <Card style={{ marginBottom: 16 }}>
        <Typography.Title level={4}>费用账单</Typography.Title>
        <ProTable
          loading={invoicesQ.isLoading}
          rowKey="invoice_uuid"
          search={false}
          dataSource={invoicesQ.data || []}
          columns={[
            { title: "账期", dataIndex: "period_month" },
            { title: "Tokens", dataIndex: "total_tokens" },
            { title: "金额", dataIndex: "total_amount" },
            { title: "状态", dataIndex: "status" },
          ]}
        />
      </Card>
      <Card>
        <Typography.Title level={4}>Token 明细</Typography.Title>
        <ProTable
          loading={eventsQ.isLoading}
          rowKey="event_uuid"
          search={false}
          dataSource={eventsQ.data || []}
          columns={[
            { title: "UUID", dataIndex: "event_uuid" },
            { title: "类型", dataIndex: "event_type" },
            { title: "Tokens", dataIndex: "total_tokens" },
            { title: "状态", dataIndex: "status" },
          ]}
        />
      </Card>
    </>
  );
}
