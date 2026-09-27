import { SupabaseClient } from "@supabase/supabase-js";

export type FarmOverviewRow = {
  farm_id: string;
  farm_name: string;
  farm_created_at: string;
  cameras_count: number;
  device_last_seen: string | null;
  events_24h: number;
  last_event_at: string | null;
};

export async function getFarmOverview(client: SupabaseClient): Promise<FarmOverviewRow[]> {
  const { data, error } = await client
    .from("admin_farm_overview")
    .select("*")
    .order("farm_created_at", { ascending: false });

  if (error) {
    throw new Error(`Не удалось загрузить список ферм: ${error.message}`);
  }
  return (data as FarmOverviewRow[]) ?? [];
}

export type CameraRow = {
  id: string;
  farm_id: string;
  name: string;
  source_uri: string;
  placement: string;
  stream_url: string | null;
  security_enabled: boolean;
  cm_per_pixel: number | null;
  created_at: string;
};

export async function getCameras(
  client: SupabaseClient,
  farmId: string
): Promise<CameraRow[]> {
  const { data, error } = await client
    .from("cameras")
    .select(
      "id, farm_id, name, source_uri, placement, stream_url, security_enabled, cm_per_pixel, created_at"
    )
    .eq("farm_id", farmId)
    .order("created_at", { ascending: true });

  if (error) {
    throw new Error(`Не удалось загрузить камеры: ${error.message}`);
  }
  return (data as CameraRow[]) ?? [];
}

/** Прячет пароль внутри rtsp://логин:пароль@адрес при показе в интерфейсе. */
export function maskStreamUrl(uri: string): string {
  return uri.replace(/(rtsp:\/\/[^:/@]+:)([^@]+)(@)/i, "$1••••$3");
}
