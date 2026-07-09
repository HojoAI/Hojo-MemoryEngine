import { LogoutOutlined } from "@ant-design/icons";
import { ProLayout, PageContainer } from "@ant-design/pro-components";
import { Button, Spin } from "antd";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import SchemaPage from "../pages/SchemaPage";
import MemoryDataPage from "../pages/MemoryDataPage";
import BillingPage from "../pages/BillingPage";
import GovernancePage from "../pages/GovernancePage";
import RulesPage from "../pages/RulesPage";
import UsersPage from "../pages/UsersPage";
import SettingsPage from "../pages/SettingsPage";

const menu = [
  { path: "/schema", name: "Schema 管理" },
  { path: "/rules", name: "规则（只读）" },
  { path: "/data", name: "记忆数据" },
  { path: "/billing", name: "计费" },
  { path: "/users", name: "用户管理" },
  { path: "/governance", name: "治理 / Dreaming" },
  { path: "/settings", name: "设置" },
];

export default function ProtectedLayout() {
  const navigate = useNavigate();
  const { user, loading, signOut, supabaseEnabled } = useAuth();

  if (supabaseEnabled && loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", marginTop: 120 }}>
        <Spin size="large" tip="加载会话…" />
      </div>
    );
  }

  if (supabaseEnabled && !user) {
    return <Navigate to="/login" replace />;
  }

  return (
    <ProLayout
      title="Memory Engine"
      layout="mix"
      route={{ routes: menu.map((m) => ({ path: m.path, name: m.name })) }}
      menuItemRender={(item, dom) => (
        <a onClick={() => item.path && navigate(item.path)}>{dom}</a>
      )}
      avatarProps={
        user
          ? {
              title: user.email ?? "用户",
              render: (_props, dom) => (
                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {dom}
                  <Button
                    type="text"
                    icon={<LogoutOutlined />}
                    onClick={async () => {
                      await signOut();
                      navigate("/login");
                    }}
                  >
                    退出
                  </Button>
                </span>
              ),
            }
          : undefined
      }
    >
      <PageContainer>
        <Routes>
          <Route path="/" element={<SchemaPage />} />
          <Route path="/schema" element={<SchemaPage />} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/data" element={<MemoryDataPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/governance" element={<GovernancePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </PageContainer>
    </ProLayout>
  );
}
