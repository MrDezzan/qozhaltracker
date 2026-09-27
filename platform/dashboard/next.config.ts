import type { NextConfig } from "next";

/**
 * ЗАГОЛОВКИ БЕЗОПАСНОСТИ
 *
 * Про каждый написано, зачем он здесь, потому что заголовки, поставленные
 * «на всякий случай», однажды ломают приложение, и никто не помнит, можно
 * ли их трогать.
 *
 * Отдельно про Content-Security-Policy. В ней стоят 'unsafe-inline' и
 * 'unsafe-eval' для скриптов — без них Next.js в текущем виде не работает:
 * он встраивает разметку гидрации прямо в страницу. Строгая политика с
 * одноразовыми метками (nonce) требует middleware и переписывания мест, где
 * стили задаются в атрибуте style. Это отдельная работа, и делать её
 * наспех хуже, чем не делать: сломанная CSP обычно кончается тем, что её
 * молча отключают целиком.
 *
 * Что политика даёт уже сейчас, даже в таком виде:
 *   frame-ancestors 'none'   — страницу нельзя вставить в чужой iframe;
 *   object-src 'none'        — нет Flash и подобных плагинов;
 *   base-uri 'self'          — нельзя подменить базовый адрес и увести
 *                              относительные ссылки на чужой хост;
 *   form-action 'self'       — форму нельзя отправить наружу;
 *   img/connect/font-src     — перечислены только нужные источники.
 */
const ЗАГОЛОВКИ = [
  {
    // Кликджекинг: без этого нашу страницу можно положить прозрачным
    // слоем поверх чужой и собирать нажатия
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    // Браузер не должен угадывать тип содержимого: угаданный text/html
    // там, где ожидалась картинка, — это выполненный скрипт
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    // В Referer на чужие сайты уходит только origin, без пути. Путь у нас
    // содержит идентификаторы ферм и животных
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    // Ничего из этого приложению не нужно, а камера и микрофон в списке
    // именно потому, что продукт про камеры: разрешение не должно
    // спрашиваться случайно
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
  {
    // Только по HTTPS, включая поддомены. Год — рекомендованный минимум;
    // preload не включён намеренно: он необратим, и решение о нём
    // принимается, когда домен окончательный
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' https://fonts.gstatic.com data:",
      "img-src 'self' data: blob: https:",
      "connect-src 'self' https://*.supabase.co wss://*.supabase.co",
      "media-src 'self' blob: https:",
      "frame-ancestors 'none'",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "upgrade-insecure-requests",
    ].join("; "),
  },
];

const nextConfig: NextConfig = {
  // Версия Next.js в заголовке ответа — бесплатная подсказка тому, кто
  // подбирает известные уязвимости под конкретный выпуск
  poweredByHeader: false,

  experimental: {
    serverActions: {
      // По умолчанию около мегабайта. Файлы через серверные действия мы
      // больше не шлём — эталонные фото уходят из браузера прямо в
      // хранилище, — поэтому запас вернули к умолчанию: лишние мегабайты
      // это только лишний способ занять память сервера.
      bodySizeLimit: "1mb",
    },
  },

  async headers() {
    return [{ source: "/:path*", headers: ЗАГОЛОВКИ }];
  },
};

export default nextConfig;
