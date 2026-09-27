import { SupabaseClient } from "@supabase/supabase-js";

export const SNAPSHOT_BUCKET = "snapshots";

/** Тот же путь, что использует устройство: {farm_id}/{camera_id}.jpg */
export function snapshotPath(farmId: string, cameraId: string): string {
  return `${farmId}/${cameraId}.jpg`;
}

export type CameraSnapshot = {
  cameraId: string;
  cameraName: string;
  url: string | null;
  /**
   * Адрес кадра на нашем сервере. Прямую ссылку в хранилище больше не
   * отдаём: по ней приходила копия из сети доставки, а не свежий кадр.
   */
  liveUrl: string | null;
  /**
   * Настроен ли на камере поток с устройства. Сам адрес наружу не отдаём:
   * в нём пароль, и браузеру он не нужен — поток идёт через наш сервер.
   */
  hasStream: boolean;
  updatedAt: string | null;
};

/**
 * Адрес кадра через наш сервер.
 *
 * Метка времени обязательна: без неё браузер отдаст свою копию, даже когда
 * сервер просит не кэшировать.
 */
export function frameUrl(cameraId: string): string {
  return `/api/frame/${cameraId}`;
}

/** Адрес видеопотока через наш сервер. Пароль к устройству туда не входит. */
export function streamUrl(cameraId: string): string {
  return `/api/stream/${cameraId}`;
}

/**
 * Ссылка на снимок подписывается на короткий срок: bucket приватный,
 * иначе кадры с чужой фермы утекли бы по прямой ссылке.
 */
export async function getSnapshotUrl(
  client: SupabaseClient,
  farmId: string,
  cameraId: string,
  expiresInSeconds = 120
): Promise<string | null> {
  const { data, error } = await client.storage
    .from(SNAPSHOT_BUCKET)
    .createSignedUrl(snapshotPath(farmId, cameraId), expiresInSeconds);

  if (error || !data) return null;
  return data.signedUrl;
}

/** Когда снимок последний раз обновлялся — чтобы отличить свежий от вчерашнего. */
export async function getSnapshotUpdatedAt(
  client: SupabaseClient,
  farmId: string,
  cameraId: string
): Promise<string | null> {
  const { data, error } = await client.storage
    .from(SNAPSHOT_BUCKET)
    .list(farmId, { search: `${cameraId}.jpg`, limit: 1 });

  if (error || !data || data.length === 0) return null;
  const file = data[0];
  return file.updated_at ?? file.created_at ?? null;
}

export async function getCameraSnapshots(
  client: SupabaseClient,
  farmId: string,
  cameras: { id: string; name: string; stream_url?: string | null }[]
): Promise<CameraSnapshot[]> {
  return Promise.all(
    cameras.map(async (camera) => ({
      cameraId: camera.id,
      cameraName: camera.name,
      url: frameUrl(camera.id),
      liveUrl: frameUrl(camera.id),
      hasStream: Boolean(camera.stream_url),
      updatedAt: await getSnapshotUpdatedAt(client, farmId, camera.id),
    }))
  );
}

/** Снимок считается устаревшим, если давно не обновлялся. */
export function isSnapshotStale(
  updatedAt: string | null,
  now: Date = new Date(),
  thresholdMinutes = 5
): boolean {
  if (!updatedAt) return true;
  return now.getTime() - new Date(updatedAt).getTime() > thresholdMinutes * 60 * 1000;
}
