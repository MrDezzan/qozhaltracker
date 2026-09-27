import { TopNav } from "../../components/ui/TopNav";
import { BottomNav } from "../../components/ui/BottomNav";
import { demoAlerts } from "../../lib/demo/events";

/**
 * Свой макет: те же полосы разделов, но ссылки ведут внутрь показа.
 *
 * Без этого человек, нажавший «Тревоги», уходил бы на живую ферму, где
 * его встретит страница входа. На показе это выглядит как сломанная
 * платформа, а не как защита.
 *
 * Счётчик тревог считается из тех же данных, что и страница тревог:
 * число на полосе и число на экране должны совпадать, иначе первый же
 * внимательный человек это заметит.
 */
export default function DemoLayout({ children }: { children: React.ReactNode }) {
  const { open } = demoAlerts(new Date());
  const срочные = open.filter((a) => a.severity !== "info").length;

  return (
    <>
      <TopNav alertCount={срочные} basePath="/demo" />
      {children}
      <BottomNav alertCount={срочные} basePath="/demo" />
    </>
  );
}
