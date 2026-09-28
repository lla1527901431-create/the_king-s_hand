-- ============================================================================
-- The King's Hand —— 清理模板遗留表（跑 01_schema.sql 之前执行）
-- ============================================================================
-- 背景：你的库里已经有两张 Supabase 模板留下的表
--         events   (start, end)          ← 列名和我设计的不一样（我用 start_at/end_at）
--         profiles (id, email, full_name, avatar_url)  ← 这个要保留
--       其中 events 已经被确认是 0 行（没有任何数据），所以可以删掉重建。
--
-- ⚠️ 这个脚本带三重保险，任何一条不满足都会中止并告诉你原因：
--      ① events 表不存在  → 跳过（没什么可删的）
--      ② events 表有数据  → 中止，不删，并告诉你有多少行
--      ③ 只有确认为 0 行  → 才真的 drop
--
-- profiles 表**不会被动**（它是模板的标准产物，且注册触发器依赖它）。
-- ============================================================================

do $$
declare
  v_exists  boolean;
  v_rows    bigint;
begin
  -- ① 表在不在？
  select exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'events'
  ) into v_exists;

  if not v_exists then
    raise notice '【跳过】public.events 不存在，无需清理。可以直接执行 01_schema.sql';
    return;
  end if;

  -- ② 有没有数据？
  execute 'select count(*) from public.events' into v_rows;

  if v_rows > 0 then
    raise exception
      '【已中止】public.events 里还有 % 行数据，脚本不会删除它。请先自行备份或迁移，然后再重跑本脚本。',
      v_rows;
  end if;

  -- ③ 确认是空表，安全删除（CASCADE 会一并带走它上面的策略和触发器）
  drop table public.events cascade;
  raise notice '【完成】已删除空的 public.events（连带其 RLS 策略与触发器）。';
  raise notice '下一步：执行 01_schema.sql 重建。';
end $$;

-- ---------------------------------------------------------------------------
-- 核对：现在库里的表应当只剩 profiles（如果你之前跑过别的，也可能更多）
-- 期望结果：只剩下 profiles 一行
-- ---------------------------------------------------------------------------
select
  t.table_name,
  (select count(*) from information_schema.columns c
     where c.table_schema = 'public' and c.table_name = t.table_name) as col_cnt,
  (select string_agg(c.column_name, ', ' order by c.ordinal_position)
     from information_schema.columns c
     where c.table_schema = 'public' and c.table_name = t.table_name) as columns
from information_schema.tables t
where t.table_schema = 'public' and t.table_type = 'BASE TABLE'
order by t.table_name;
