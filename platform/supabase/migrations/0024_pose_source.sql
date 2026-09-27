-- ---------------------------------------------------------------------------
-- Откуда взяты промеры: описанный прямоугольник или ключевые точки
-- ---------------------------------------------------------------------------
-- Два способа дают разные величины под одними именами. Прямоугольник
-- вокруг маски удлиняется от поднятой руки, хвоста и тени на краю
-- контура; расстояние плечо–лодыжка от этого не зависит. Числа
-- отличаются систематически, и если сложить их в один столбец, формула
-- веса примет разницу способов за разницу телосложений.
--
-- Поэтому источник пишется рядом с промером, а подбор формулы идёт
-- только по одному источнику.

alter table body_measurements
  add column if not exists source text not null default 'rect'
    check (source in ('rect', 'pose'));

comment on column body_measurements.source is
  'rect — стороны описанного прямоугольника, pose — расстояния между ключевыми точками';

create index if not exists body_measurements_source_idx
  on body_measurements (farm_id, source, measured_at desc);

-- ---------------------------------------------------------------------------
-- Подбор формулы — по одному источнику
-- ---------------------------------------------------------------------------
-- Берём тот источник, которым сделано больше промеров с сантиметрами.
-- Не «самый свежий»: одна ночь работы новой камеры не должна выкидывать
-- накопленную историю. И не оба сразу — ради чего вся эта миграция.

create or replace function dominant_measure_source(target_farm_id uuid)
returns text
language sql
stable
set search_path = public
as $$
  select m.source
  from body_measurements m
  where m.farm_id = target_farm_id
    and m.length_cm is not null
    and m.width_cm is not null
  group by m.source
  order by count(*) desc, m.source
  limit 1
$$;

create or replace function weight_training_pairs_cm(target_farm_id uuid)
returns table (
  animal_id uuid,
  weight_kg double precision,
  length_cm double precision,
  width_cm double precision,
  volume_proxy double precision
)
language sql
stable
set search_path = public
as $$
  select
    w.animal_id,
    w.weight_kg,
    avg(m.length_cm) as length_cm,
    avg(m.width_cm) as width_cm,
    avg(m.length_cm * m.width_cm * m.width_cm) as volume_proxy
  from weighings w
  join body_measurements m
    on m.animal_id = w.animal_id
   and m.quality >= 0.8
   and m.length_cm is not null
   and m.width_cm is not null
   -- Только преобладающий источник: смешивать прямоугольник с точками
   -- значит подсовывать формуле два разных признака под одним именем
   and m.source = dominant_measure_source(target_farm_id)
   and m.measured_at between w.weighed_at - interval '3 days'
                        and w.weighed_at + interval '3 days'
  where w.farm_id = target_farm_id
  group by w.id, w.animal_id, w.weight_kg
$$;

revoke all on function dominant_measure_source(uuid) from public;
grant execute on function dominant_measure_source(uuid) to authenticated;
