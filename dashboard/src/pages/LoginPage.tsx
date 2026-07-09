import { LockOutlined, MailOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Form, Input, Space, Tabs, Typography, message } from "antd";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { formatAuthError, isEmailNotConfirmed } from "../lib/authErrors";

export default function LoginPage() {
  const { user, loading, signIn, signUp, resendConfirmationEmail, supabaseEnabled } = useAuth();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [pendingEmail, setPendingEmail] = useState<string | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);

  if (!supabaseEnabled) {
    return (
      <div style={{ maxWidth: 480, margin: "80px auto", padding: 24 }}>
        <Alert
          type="warning"
          message="未配置 Supabase"
          description="请在 dashboard/.env.local 中设置 VITE_SUPABASE_URL 与 VITE_SUPABASE_ANON_KEY。"
          showIcon
        />
        <Button type="link" onClick={() => navigate("/settings")} style={{ marginTop: 16 }}>
          前往设置（API Key）
        </Button>
      </div>
    );
  }

  if (!loading && user) {
    return <Navigate to="/schema" replace />;
  }

  const handleResend = async (email: string) => {
    try {
      await resendConfirmationEmail(email);
      message.success("确认邮件已重新发送，请检查收件箱与垃圾箱");
    } catch (e: unknown) {
      message.error(formatAuthError(e));
    }
  };

  const onFinish = async (values: { email: string; password: string }, mode: "login" | "signup") => {
    setSubmitting(true);
    setLoginError(null);
    setPendingEmail(values.email);
    try {
      if (mode === "login") {
        await signIn(values.email, values.password);
        message.success("登录成功");
        navigate("/schema");
      } else {
        const result = await signUp(values.email, values.password);
        if (result.needsEmailConfirmation) {
          message.warning("注册成功，请先完成邮箱验证后再登录");
          setLoginError(
            "已向您的邮箱发送确认链接。若未收到邮件，请检查垃圾箱，或点击下方「重发确认邮件」。",
          );
        } else {
          message.success("注册成功，已自动登录");
          navigate("/schema");
        }
      }
    } catch (e: unknown) {
      const text = formatAuthError(e);
      setLoginError(text);
      message.error(text);
      if (isEmailNotConfirmed(e)) {
        setPendingEmail(values.email);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const form = (mode: "login" | "signup") => (
    <Form
      layout="vertical"
      onFinish={(v) => onFinish(v, mode)}
      initialValues={{ email: pendingEmail ?? undefined }}
    >
      <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email" }]}>
        <Input prefix={<MailOutlined />} placeholder="you@example.com" />
      </Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true, min: 6 }]}>
        <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={submitting}>
        {mode === "login" ? "登录" : "注册"}
      </Button>
    </Form>
  );

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg, #f0f5ff 0%, #fff 50%)",
      }}
    >
      <Card style={{ width: 440 }} title={<Typography.Title level={3}>Memory Engine Dashboard</Typography.Title>}>
        <Typography.Paragraph type="secondary">
          使用 Supabase 账号登录；业务 API 仍须在「设置」中配置 Memory Engine API Key。
        </Typography.Paragraph>

        {loginError && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="无法登录"
            description={
              <Space direction="vertical" style={{ width: "100%" }}>
                <span>{loginError}</span>
                {pendingEmail && (
                  <Button size="small" onClick={() => handleResend(pendingEmail)}>
                    重发确认邮件
                  </Button>
                )}
              </Space>
            }
          />
        )}

        <Tabs
          items={[
            { key: "login", label: "登录", children: form("login") },
            { key: "signup", label: "注册", children: form("signup") },
          ]}
        />

        <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12 }}>
          开发环境收不到邮件？在 Supabase → Authentication → Providers → Email 中关闭「Confirm
          email」。也可先
          <Button type="link" size="small" onClick={() => navigate("/settings")} style={{ padding: 0 }}>
            仅用 API Key 进入设置
          </Button>
        </Typography.Paragraph>
      </Card>
    </div>
  );
}
