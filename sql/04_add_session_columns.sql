-- ============================================================================
-- The King's Hand —— 给 user_secrets 加"会话续期凭据"字段
-- ============================================================================
-- 背景：采用 HttpOnly Cookie 方案后，refresh_token 不能放在浏览器里
--       （那等于把长期钥匙交给 JS）。所以改成加密后存在服务端数据库里。
--
-- 新增两列：
--   refresh_token  加密后的 refresh_token（AES-256-GCM，主密钥在服务器）
--   session_iat    session 建立时间，用于排查"这个登录态是什么时候建的"
--
-- 即使数据库被拖库，攻击者拿到的也只是密文；主密钥不在数据库里。
-- 本脚本可重复执行。
-- ============================================================================

alter table public.user_secrets
  add column if not exists refresh_token text;

alter table public.user_secrets
  add column if not exists session_iat timestamptz;

-- 取消会话时用：清空这两列就够了，不必删整行（用户的 API key 要保留）
comment on column public.user_secrets.refresh_token is
  '加密后的 Supabase refresh_token，用于 HttpOnly cookie 会话续期';

-- 核对：user_secrets 现在应当是 7 列
select
  (select count(*) from information_schema.columns
     where table_schema = 'public' and table_name = 'user_secrets') as col_cnt,
  (select string_agg(column_name, ', ' order by ordinal_position)
     from information_schema.columns
     where table_schema = 'public' and table_name = 'user_secrets') as columns;
