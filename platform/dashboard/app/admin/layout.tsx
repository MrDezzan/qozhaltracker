import { redirect } from "next/navigation";
import { getServerSupabase } from "../../lib/supabaseServer";
import { requireAdmin } from "../../lib/adminGuard";
import { НЕ_ВОШЁЛ } from "../../lib/auth";
import { AdminSidebar } from "../../components/AdminSidebar";

export const dynamic = "force-dynamic";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const supabase = await getServerSupabase();

  // Единственная точка проверки прав для всего раздела /admin.
  // Настоящая защита — политики в БД; это лишь чтобы не показывать пустые экраны.
  try {
    await requireAdmin(supabase);
  } catch (e) {
    // Сравнение с общей константой, а не с куском текста: раньше здесь
    // стояло message.includes("не авторизован"), и стоило переписать
    // саму ошибку, как незалогиненный админ уезжал на главную вместо
    // страницы входа. Молча: оба пути ведут на живой экран
    const message = e instanceof Error ? e.message : String(e);
    if (message === НЕ_ВОШЁЛ) {
      redirect("/login");
    }
    redirect("/");
  }

  return (
    <div className="flex flex-col sm:flex-row min-h-screen">
      <AdminSidebar />
      <div className="flex-1 min-w-0 px-4 sm:px-10 py-6 sm:py-9">
        <div className="max-w-5xl">{children}</div>
      </div>
    </div>
  );
}
