-- ============================================================================
-- The King's Hand —— Supabase 建表脚本（第 1 步）
-- ============================================================================
-- 用法：Supabase 控制台 → 左侧 SQL Editor → New query → 全文粘贴 → Run
--
-- 这个脚本做四件事：
--   1. 建 4 张表：events / pending_tasks / memories / user_secrets
--   2. 每张表都开启 RLS（行级安全），策略是"只能碰自己的行"
--   3. 建索引、约束、updated_at 自动维护
--   4. 最后自带一个自检，会打印 4 张表各自的 RLS 状态
--
-- 设计要点：
--   * 一人一"空间"，不是一个库一个库：所有用户共用这些表，靠 user_id + RLS 隔离
--   * user_id 默认取 auth.uid()，也就是说"谁插的数据就归谁"，无需前端传
--   * RLS 的 insert 策略写成 auth.uid() = user_id，所以"往别人名下写"会被数据库直接拒绝
--   * 可重复执行：所有语句都带 if not exists / drop policy if exists
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 0. 触发器函数：任何一行被更新时，自动刷新 updated_at
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;


-- ---------------------------------------------------------------------------
-- 1. 日历事件表（原来存在 data/events.json）
--
--    ⚠️ 这里不能简单写 create table if not exists：
--       你的库里本来就有个模板留下的 public.events（列名是 start / end），
--       if not exists 只认表名、不认结构，会静默跳过，
--       然后下面建索引时引用 start_at 就会报一个跟真实原因无关的
--       42703: column "start_at" does not exist。
--       所以这里先检测、再决定"能不能安全重建"，检测不过就报一条看得懂的错。
-- ---------------------------------------------------------------------------
do $$
declare
  v_exists boolean;
  v_ok     boolean;
  v_rows   bigint;
begin
  select exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'events'
  ) into v_exists;

  if v_exists then
    -- 表已存在：结构对不对？（认 user_id + start_at + end_at 这三个列）
    select (
      select count(*) from information_schema.columns
      where table_schema = 'public' and table_name = 'events'
        and column_name in ('user_id', 'start_at', 'end_at')
    ) = 3 into v_ok;

    if v_ok then
      raise notice '【跳过】public.events 已存在且结构正确。';
      return;
    end if;

    -- 结构不对：如果它是空表，就自动重建，省得你再去跑一次 00_reset.sql
    execute 'select count(*) from public.events' into v_rows;

    if v_rows = 0 then
      raise notice '【重建】public.events 结构不匹配但为空（0 行），自动删除后重建。';
      drop table public.events cascade;
    else
      raise exception
        '【已中止】public.events 已存在、结构不匹配（缺少 start_at/end_at），且里面有 % 行数据。请先执行 00_reset.sql 查看并处理。',
        v_rows;
    end if;
  end if;

  create table public.events (
    id          text        primary key,
    user_id     uuid        not null default auth.uid()
                            references auth.users (id) on delete cascade,
    title       text        not null check (length(btrim(title)) > 0),
    start_at    timestamptz not null,
    end_at      timestamptz,
    location    text        not null default '',
    note        text        not null default '',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    -- 结束时间不能早于开始时间（允许为空 = 未知时长）
    constraint events_time_order check (end_at is null or end_at >= start_at)
  );

  raise notice '【完成】public.events 已创建。';
end $$;

create index if not exists events_user_start_idx
  on public.events (user_id, start_at);

create or replace trigger events_set_updated_at
  before update on public.events
  for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------------
-- 2. 待确认 / 待计划任务表（原来存在 data/pending.json）
--    原来用 {"confirmed": [...], "planned": [...]} 两个数组表达分组，
--    这里改成一个 bucket 字段，读写时再组装回原来的形状。
-- ---------------------------------------------------------------------------
create table if not exists public.pending_tasks (
  id          text        primary key,
  user_id     uuid        not null default auth.uid()
                          references auth.users (id) on delete cascade,
  title       text        not null check (length(btrim(title)) > 0),
  start_at    timestamptz,
  end_at      timestamptz,
  location    text        not null default '',
  note        text        not null default '',
  -- 有明确开始时间 → confirmed（待确认）；没有 → planned（待计划）
  bucket      text        not null default 'planned'
                          check (bucket in ('confirmed', 'planned')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint pending_time_order check (
    end_at is null or start_at is null or end_at >= start_at
  )
);

create index if not exists pending_user_bucket_idx
  on public.pending_tasks (user_id, bucket, created_at);

create or replace trigger pending_tasks_set_updated_at
  before update on public.pending_tasks
  for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------------
-- 3. 长期记忆表（原来存在 data/memory.json）
--
--    三块内容：
--      facts        —— 用户明确说过的事实（身份、单位、学历…）
--      observations —— 观察台账：[{"text": "...", "at": "YYYY-MM-DD"}]。
--                      每条只记"某次发生了什么"，不急着下结论。
--                      同一个现象被观察到多次时，才升级成 preferences。
--      preferences  —— 稳定的偏好与习惯（可以由 observations 归纳而来）
--
--    一个用户只有一行。
-- ---------------------------------------------------------------------------
create table if not exists public.memories (
  user_id      uuid        primary key
                           default auth.uid()
                           references auth.users (id) on delete cascade,
  facts        jsonb       not null default '[]'::jsonb,
  observations jsonb       not null default '[]'::jsonb,
  preferences  jsonb       not null default '[]'::jsonb,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- 如果表是更早的版本（只有 facts / preferences），补上 observations 列
alter table public.memories
  add column if not exists observations jsonb not null default '[]'::jsonb;

create or replace trigger memories_set_updated_at
  before update on public.memories
  for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------------
-- 4. 用户凭据表（新增）—— 存用户自己填的 DeepSeek key / QQ 邮箱授权码
--
--    ⚠️ 重要：这里存的是**密文**，不是明文。
--    密文由后端用 AES-256-GCM 加密后写入，主密钥只在服务器上，不进数据库。
--    数据库被拖库时，攻击者拿到的是 "gAAAAAB..." 这种字符串，解不开。
--
--    payload 的 JSON 形状：
--      {
--        "deepseek_key": "密文",
--        "smtp_user":    "用户的QQ邮箱（明文，不算敏感）",
--        "smtp_pass":    "密文",
--        "updated_at":   "2026-09-28T09:30:00"
--      }
--    注意：解出来的明文**只存在于后端内存中，用完即弃，绝不写日志**。
-- ---------------------------------------------------------------------------
create table if not exists public.user_secrets (
  user_id       uuid        primary key
                            default auth.uid()
                            references auth.users (id) on delete cascade,
  payload       jsonb       not null default '{}'::jsonb,
  key_version   integer     not null default 1,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create or replace trigger user_secrets_set_updated_at
  before update on public.user_secrets
  for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------------
-- 5. 开启 RLS 并建立"只能碰自己行"的策略
--    RLS = Row Level Security，行级安全。它是这次改造的核心：
--    即使后端代码写错了、忘了加 where user_id，数据库也只会返回当前登录用户的行。
-- ---------------------------------------------------------------------------
alter table public.events        enable row level security;
alter table public.pending_tasks enable row level security;
alter table public.memories      enable row level security;
alter table public.user_secrets  enable row level security;

-- events -------------------------------------------------------------------
drop policy if exists events_select_own on public.events;
create policy events_select_own on public.events
  for select to authenticated using (auth.uid() = user_id);

drop policy if exists events_insert_own on public.events;
create policy events_insert_own on public.events
  for insert to authenticated with check (auth.uid() = user_id);

drop policy if exists events_update_own on public.events;
create policy events_update_own on public.events
  for update to authenticated
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists events_delete_own on public.events;
create policy events_delete_own on public.events
  for delete to authenticated using (auth.uid() = user_id);

-- pending_tasks ------------------------------------------------------------
drop policy if exists pending_select_own on public.pending_tasks;
create policy pending_select_own on public.pending_tasks
  for select to authenticated using (auth.uid() = user_id);

drop policy if exists pending_insert_own on public.pending_tasks;
create policy pending_insert_own on public.pending_tasks
  for insert to authenticated with check (auth.uid() = user_id);

drop policy if exists pending_update_own on public.pending_tasks;
create policy pending_update_own on public.pending_tasks
  for update to authenticated
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists pending_delete_own on public.pending_tasks;
create policy pending_delete_own on public.pending_tasks
  for delete to authenticated using (auth.uid() = user_id);

-- memories -----------------------------------------------------------------
drop policy if exists memories_select_own on public.memories;
create policy memories_select_own on public.memories
  for select to authenticated using (auth.uid() = user_id);

drop policy if exists memories_insert_own on public.memories;
create policy memories_insert_own on public.memories
  for insert to authenticated with check (auth.uid() = user_id);

drop policy if exists memories_update_own on public.memories;
create policy memories_update_own on public.memories
  for update to authenticated
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists memories_delete_own on public.memories;
create policy memories_delete_own on public.memories
  for delete to authenticated using (auth.uid() = user_id);

-- user_secrets -------------------------------------------------------------
drop policy if exists user_secrets_select_own on public.user_secrets;
create policy user_secrets_select_own on public.user_secrets
  for select to authenticated using (auth.uid() = user_id);

drop policy if exists user_secrets_insert_own on public.user_secrets;
create policy user_secrets_insert_own on public.user_secrets
  for insert to authenticated with check (auth.uid() = user_id);

drop policy if exists user_secrets_update_own on public.user_secrets;
create policy user_secrets_update_own on public.user_secrets
  for update to authenticated
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists user_secrets_delete_own on public.user_secrets;
create policy user_secrets_delete_own on public.user_secrets
  for delete to authenticated using (auth.uid() = user_id);


-- ---------------------------------------------------------------------------
-- 6. 自检：执行完应当看到 4 行，且 rls_enabled 全部为 true、
--    policy 数量分别为 events=4 / pending_tasks=4 / memories=4 / user_secrets=4
-- ---------------------------------------------------------------------------
select
  c.relname                                        as table_name,
  c.relrowsecurity                                 as rls_enabled,
  (select count(*) from pg_policies p
     where p.schemaname = 'public' and p.tablename = c.relname) as policy_count
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('events', 'pending_tasks', 'memories', 'user_secrets')
order by c.relname;
