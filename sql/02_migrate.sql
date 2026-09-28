-- ============================================================================
-- The King's Hand —— 把本地旧数据迁移到你的账号下（第 6 步）
-- ============================================================================
-- 前置条件（三个都要满足，否则会失败或插错地方）：
--   1. 已经执行过 01_schema.sql
--   2. 你已经在这个项目的网页上用邮箱注册过账号
--   3. 你此刻是在 Supabase 控制台的 SQL Editor 里执行（有登录会话）
--
-- 数据来源：项目里的 data/events.json、data/pending.json、data/memory.json
-- 迁移后会：
--   * 7 条课程事件 → events 表
--   * 2 条待办     → pending_tasks 表（都是 planned，因为没有具体时间）
--   * 3 条事实 + 2 条偏好 → memories 表
--
-- 这个脚本可以安全重复执行（id 是写死的固定值，重复跑会被主键冲突挡掉）。
-- 想先看看自己的数据长什么样，见文件末尾的"核对查询"。
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 0. 先确认"当前登录用户"，以及你名下现在有多少数据
--    执行前请先看这一段的输出：user_id 应当是你在 auth.users 里的 id
-- ---------------------------------------------------------------------------
select auth.uid() as my_user_id,
       (select count(*) from public.events        where user_id = auth.uid()) as existing_events,
       (select count(*) from public.pending_tasks where user_id = auth.uid()) as existing_pending,
       (select count(*) from public.memories      where user_id = auth.uid()) as existing_memories;


-- ---------------------------------------------------------------------------
-- 1. 迁移 7 条课程事件
--    原 JSON 里的 8 位 id（如 "5e6f62c3"）改用固定的 uuid，
--    避免和以后自动生成的短 id 撞车，同时让脚本可重复执行。
-- ---------------------------------------------------------------------------
insert into public.events (id, title, start_at, end_at, location, note, created_at, updated_at)
values
  ('10000000-0000-4000-8000-000000000001', '信息论与编码技术',   timestamptz '2026-09-22 08:15+08', timestamptz '2026-09-22 09:50+08', '马兰芳404', 'zzh帮我代课', now(), now()),
  ('10000000-0000-4000-8000-000000000002', '信息论与编码技术',   timestamptz '2026-09-24 08:15+08', timestamptz '2026-09-24 09:50+08', '马兰芳404', '',            now(), now()),
  ('10000000-0000-4000-8000-000000000003', '电磁场与微波技术',   timestamptz '2026-09-22 19:30+08', timestamptz '2026-09-22 21:05+08', '',          '晚课',        now(), now()),
  ('10000000-0000-4000-8000-000000000004', '电磁场与微波技术',   timestamptz '2026-09-23 19:30+08', timestamptz '2026-09-23 21:05+08', '',          '晚课',        now(), now()),
  ('10000000-0000-4000-8000-000000000005', '信息论与编码技术',   timestamptz '2026-09-29 08:15+08', timestamptz '2026-09-29 09:50+08', '',          '',            now(), now()),
  ('10000000-0000-4000-8000-000000000006', '电磁场与微波技术',   timestamptz '2026-09-29 19:30+08', timestamptz '2026-09-29 21:05+08', '',          '',            now(), now()),
  ('10000000-0000-4000-8000-000000000007', '电磁场与微波技术',   timestamptz '2026-09-30 19:30+08', timestamptz '2026-09-30 21:05+08', '',          '',            now(), now())
on conflict (id) do nothing;


-- ---------------------------------------------------------------------------
-- 2. 迁移 2 条待办（原本都在 planned 里，因为没有具体时间）
-- ---------------------------------------------------------------------------
insert into public.pending_tasks (id, title, start_at, end_at, location, note, bucket, created_at, updated_at)
values
  ('20000000-0000-4000-8000-000000000001', '约人打篮球', null, null, '',
   '暂定周六（9/26）下午，具体时间未定；户外活动。9/26 为中毛毛雨、降水概率42%，如遇雨可考虑改到周五9/25或周日9/27（均为晴间多云，降水概率约27%）',
   'planned', now(), now()),
  ('20000000-0000-4000-8000-000000000002', '去珠海拿资料', null, null, '珠海',
   '需在 16:30 江门会议前完成；深圳→珠海→江门跨城，路上留足时间',
   'planned', now(), now())
on conflict (id) do nothing;


-- ---------------------------------------------------------------------------
-- 3. 迁移长期记忆（一个用户一行，所以用 upsert）
--
--    ⚠️ 已被人工清理、**不迁移**的内容（这些都是 LLM 蒸馏时自己推断出来的）：
--       "用户有课程信息论与编码技术，课程时间为周四上午8:15-9:50；
--        本周二（9-29）08:15-09:50 也有一次，地点为马兰芳404"
--       "用户有课程电磁场与微波技术，课程时间为周二和周三晚上19:30-21:05，
--        地点为黄浩川202（9-29、9-30）"
--       "用户计划在10-01（周四）打篮球（具体时间待定）"
--       "用户倾向于选择降水概率最低的日期安排打篮球"
--
--    为什么清掉：模型会从"日程数据"里反推出"课表规律"，一旦推错就会固化，
--    而且后续还会在错误基础上继续叠加解释，越滚越复杂。
--    真实课表只应由用户自己确认，不应该让模型猜。
-- ---------------------------------------------------------------------------
insert into public.memories (user_id, facts, preferences, created_at, updated_at)
values (
  auth.uid(),
  '["用户是江门五邑大学的学生",
    "用户现在在深圳宝安机场数据中心实习",
    "用户是珠海户口"]'::jsonb,
  '["用户有打篮球的兴趣",
    "用户有喝咖啡的兴趣"]'::jsonb,
  now(), now()
)
on conflict (user_id) do update
  set facts       = excluded.facts,
      preferences = excluded.preferences,
      updated_at  = now();


-- ---------------------------------------------------------------------------
-- 4. 核对：迁移结果应当看到
--    events = 7 条、pending_tasks = 2 条、memories = 1 行
-- ---------------------------------------------------------------------------
select 'events'        as table_name, count(*) as rows from public.events        where user_id = auth.uid()
union all
select 'pending_tasks' as table_name, count(*) as rows from public.pending_tasks where user_id = auth.uid()
union all
select 'memories'      as table_name, count(*) as rows from public.memories      where user_id = auth.uid();

-- 逐条看看迁移后的课程事件（顺便核对星期二/星期四那件事）
select title, start_at, end_at, location, note
from public.events
where user_id = auth.uid()
order by start_at;
