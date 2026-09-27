-- Ступени разговора.
--
-- Анкета начиналась с первого же сообщения: бот здоровался, вываливал
-- всё про продукт и тут же спрашивал про поголовье. Человек ещё не
-- спросил, а ему уже отвечают и уже допрашивают.
--
-- Теперь по ступеням, и каждая следующая — с согласия:
--
--   greet          короткое знакомство и «рассказать подробнее?»
--   offered_pitch  ждём ответа на это предложение
--   offered_calc   рассказали, ждём ответа на «посчитать?»
--   survey         идёт анкета
--   free           от расчёта отказался: отвечаем, но не навязываем
--
-- КОЛОНКИ ЗДЕСЬ И В manager/schema.sql ОБЯЗАНЫ СОВПАДАТЬ.

alter table leads
  add column if not exists stage text not null default 'greet';

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'leads_stage_check'
  ) then
    alter table leads
      add constraint leads_stage_check check (stage in (
        'greet', 'offered_pitch', 'offered_calc', 'survey', 'free'));
  end if;
end $$;
