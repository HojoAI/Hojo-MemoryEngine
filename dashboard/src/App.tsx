import { Route, Routes } from "react-router-dom";
import ProtectedLayout from "./components/ProtectedLayout";
import LoginPage from "./pages/LoginPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* 未启用 Supabase 时可直接访问设置页配置 API Key */}
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/*" element={<ProtectedLayout />} />
    </Routes>
  );
}
