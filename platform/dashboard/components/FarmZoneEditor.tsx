"use client";

import { ZoneRow } from "../lib/zones";
import { ZoneEditor } from "./ZoneEditor";
import { createFarmZoneAction } from "../app/zones/actions";

/**
 * Разметка зон для аккаунта хозяйства.
 *
 * Тонкая обёртка над общим редактором: отличается только тем, кто
 * сохраняет. Админский вариант проверяет право администратора, этот —
 * принадлежность фермы. Одна функция с флагом «кто вызвал» была бы
 * короче и однажды пропустила бы проверку.
 */
export function FarmZoneEditor(props: {
  farmId: string;
  cameraId: string;
  cameraName: string;
  snapshotUrl: string | null;
  zones: ZoneRow[];
}) {
  return <ZoneEditor {...props} action={createFarmZoneAction} />;
}
