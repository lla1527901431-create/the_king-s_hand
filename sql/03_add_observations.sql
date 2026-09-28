-- ============================================================================
-- The King's Hand —— 给 memories 表加"观察台账"字段
-- ============================================================================
-- 背景：记忆蒸馏原本只有 facts / preferences 两块。这导致两种糟糕情况：
--   * 只看一次就下结论（"用户说过一次想找不下雨的日期" → 记成稳定偏好）
--   * 反过来，反复出现的行为没有落脚点，模型只能靠一句 prompt 去"记得"，
--     结果还是记不住。
--
-- 现在增加 observations：只记录"某天观察到了什么"，不下结论。
-- 同一个现象被反复观察到多次，才由蒸馏升级成 preferences。
--
-- 本脚本可重复执行（add column if not exists）。
-- ============================================================================

alter table public.memories
  add column if not exists observations jsonb not null default '[]'::jsonb;

-- 核对：应当看到 observations 列，列数从 5 变成 6
select
  t.table_name,
  (select count(*) from information_schema.columns c
     where c.table_schema = 'public' and c.table_name = t.table_name) as col_cnt,
  (select string_agg(c.column_name, ', ' order by c.ordinal_position)
     from information_schema.columns c
     where c.table_schema = 'public' and c.table_name = t.table_name) as columns
from information_schema.tables t
where t.table_schema = 'public' and t.table_name = 'memories';
