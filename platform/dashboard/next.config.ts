import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    serverActions: {
      // По умолчанию около мегабайта. Файлы через серверные действия мы
      // больше не шлём — эталонные фото уходят из браузера прямо в
      // хранилище, — но запас оставляем: превышение выглядит как
      // «Unexpected end of form», и по этому сообщению невозможно
      // догадаться, что дело в размере.
      bodySizeLimit: "4mb",
    },
  },
};

export default nextConfig;
