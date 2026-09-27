import { redirect } from "next/navigation";
import { getServerSupabase } from "../../lib/supabaseServer";
import { getTermsStatus, TERMS_VERSION } from "../../lib/terms";
import { TermsForm } from "./TermsForm";
import { Page } from "../../components/ui/Page";

export const dynamic = "force-dynamic";

export default async function TermsPage() {
  const supabase = await getServerSupabase();
  const { data: sessionData } = await supabase.auth.getUser();
  if (!sessionData.user) redirect("/login");

  const status = await getTermsStatus(supabase);
  if (status.accepted) redirect("/");

  return (
    <Page width="narrow">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-ink">Условия использования</h1>
        <p className="text-sm text-muted mt-1">
          Редакция {TERMS_VERSION}. Ознакомьтесь перед началом работы.
        </p>
      </div>

      <div className="bg-surface border border-line rounded-xl divide-y divide-line-soft">
        <Section title="Что делает система">
          Считает животных в кадре и по зонам, ведёт время у кормушек и поилок,
          узнаёт отдельных особей по записи с камеры, оценивает живую массу
          по силуэту и строит по этому отчёты. Всё — по камерам: носимых датчиков
          система не требует.
        </Section>

        <Section title="Чего система не делает">
          Не ставит ветеринарных диагнозов: отклонение — повод осмотреть животное,
          а не назначение лечения. Оценка массы расчётная и не заменяет
          взвешивание на поверенных весах — для купли-продажи и отчётности она
          непригодна. Не заменяет обязательную идентификацию животных. Не является
          охранной сигнализацией.
        </Section>

        <Section title="Ваши данные">
          Данные принадлежат вам. Видеопоток не покидает ферму — наружу уходят
          только результаты обработки: числа, события и отдельные кадры животных.
          События хранятся 400 дней, безымянные кадры — 30 дней, кадры
          предпросмотра — 7 дней. Выгрузку можно запросить в любой
          момент.
        </Section>

        <Section title="Съёмка работников" highlight>
          Если камеры видят людей, обязанность оформить это лежит на хозяйстве:
          письменное согласие каждого работника, таблички «Ведётся
          видеонаблюдение» на входах, утверждённое положение о порядке
          наблюдения. Камеры не должны смотреть в бытовые помещения, раздевалки и
          места отдыха. Готовые формы согласия и таблички передаются вместе с
          договором — оформление занимает один рабочий день.
        </Section>

        <Section title="Вход и пароль">
          Пароль показывается один раз и не восстанавливается: хранится только
          его необратимое преобразование. При утрате выпускается новый — все
          входы со старым паролем при этом прекращаются.
        </Section>

        <Section title="Ответственность">
          Решения о лечении, выбраковке, продаже и кормлении принимаете вы.
          Полнота данных зависит от электропитания и связи на ферме: при их
          отсутствии обработка продолжается на месте, а накопленное уходит после
          восстановления связи.
        </Section>
      </div>

      <p className="text-xs text-muted mt-4 leading-relaxed">
        Здесь приведены основные положения. Полный текст условий и формы согласия
        работников передаются вместе с договором.
      </p>

      <TermsForm />
    </Page>
  );
}

function Section({
  title,
  children,
  highlight = false,
}: {
  title: string;
  children: React.ReactNode;
  highlight?: boolean;
}) {
  return (
    <div className={`px-5 sm:px-6 py-5 ${highlight ? "bg-watch-bg/50" : ""}`}>
      <h2 className="text-sm font-medium text-ink">{title}</h2>
      <p className="text-sm text-muted mt-1.5 leading-relaxed">{children}</p>
    </div>
  );
}
