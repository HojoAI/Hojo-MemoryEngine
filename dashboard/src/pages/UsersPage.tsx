import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ProTable } from "@ant-design/pro-components";
import { Button, message } from "antd";
import { api } from "../lib/api";

export default function UsersPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: async () => (await api.get("/users/list")).data.data,
  });

  return (
    <ProTable
      loading={isLoading}
      rowKey="id"
      search={false}
      dataSource={data || []}
      columns={[
        { title: "ID", dataIndex: "id" },
        { title: "邮箱", dataIndex: "email" },
        { title: "显示名", dataIndex: "display_name" },
        { title: "状态", dataIndex: "status" },
        {
          title: "操作",
          render: (_, row) => (
            <Button
              danger
              size="small"
              onClick={async () => {
                await api.post("/users/delete", null, { params: { user_id: row.id } });
                message.success("已删除");
                qc.invalidateQueries({ queryKey: ["users"] });
              }}
            >
              删除
            </Button>
          ),
        },
      ]}
    />
  );
}
