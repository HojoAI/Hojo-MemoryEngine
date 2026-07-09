/** Map Supabase Auth errors to user-facing Chinese messages. */
export function formatAuthError(err: unknown): string {
  const msg =
    err && typeof err === "object" && "message" in err
      ? String((err as { message: string }).message)
      : err instanceof Error
        ? err.message
        : "认证失败";

  const lower = msg.toLowerCase();
  if (lower.includes("email not confirmed")) {
    return "邮箱尚未验证。请查收注册确认邮件（含垃圾箱），或点击下方「重发确认邮件」。";
  }
  if (lower.includes("invalid login credentials")) {
    return "邮箱或密码错误，请检查后重试。";
  }
  if (lower.includes("user already registered")) {
    return "该邮箱已注册，请直接登录或使用「重发确认邮件」。";
  }
  if (lower.includes("rate limit")) {
    return "操作过于频繁，请稍后再试。";
  }
  return msg;
}

export function isEmailNotConfirmed(err: unknown): boolean {
  const msg =
    err && typeof err === "object" && "message" in err
      ? String((err as { message: string }).message)
      : "";
  return msg.toLowerCase().includes("email not confirmed");
}
