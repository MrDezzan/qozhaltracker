from __future__ import annotations

import os
import time

from supabase import Client, create_client

from cv_service.events import AnimalEvent

# За сколько до истечения токена обновлять сессию. Токен живёт около часа;
# пяти минут запаса хватает, чтобы обновление успело пройти по медленной связи.
SESSION_REFRESH_MARGIN_S = 300.0

# Потолок ожидания ответа от базы и хранилища.
#
# Без него зависший запрос держит поток бесконечно. На ферме связь рвётся
# так, что соединение не закрывается, а просто перестаёт отвечать, — и по
# умолчанию клиент готов ждать этого вечно. Десять секунд достаточно даже
# для медленного канала, а отправку снимка лучше бросить и попробовать
# со следующим кадром, чем ждать минуту.
REQUEST_TIMEOUT_S = 10.0
STORAGE_TIMEOUT_S = 20.0


def client_options():
    """Настройки клиента с ограничением на ожидание ответа."""
    # Берём из самого пакета: у вложенного модуля набор полей другой,
    # и клиент падал на отсутствующем атрибуте
    from supabase import ClientOptions

    return ClientOptions(
        postgrest_client_timeout=REQUEST_TIMEOUT_S,
        storage_client_timeout=STORAGE_TIMEOUT_S,
    )


def sign_in(client: Client) -> None:
    """Вход по логину и паролю устройства. Отдельно — чтобы можно было повторить."""
    login = os.environ["DEVICE_LOGIN"]
    password = os.environ["DEVICE_PASSWORD"]

    result = client.auth.sign_in_with_password({"email": login, "password": password})
    if not result.session:
        raise RuntimeError(
            "Не удалось войти под учётной записью устройства. "
            "Проверьте DEVICE_LOGIN и DEVICE_PASSWORD в .env"
        )


def explain_connection_error(url: str, error: Exception) -> str:
    """
    Ошибку сети — человеческими словами.

    Сырой стек httpx на пятнадцать строк заканчивается фразой
    «nodename nor servname provided», по которой невозможно догадаться,
    что делать. А делать надо разное: при отсутствии интернета — ждать,
    при удалённом проекте — заводить новый.
    """
    text = str(error).lower()
    host = url.replace("https://", "").replace("http://", "").strip("/")

    if "nodename nor servname" in text or "name or service not known" in text or "getaddrinfo" in text:
        return (
            f"Имя {host} не разрешается в адрес. Три причины по убыванию "
            "вероятности:\n"
            "  1) на этом компьютере нет интернета или отвалился DNS — "
            f"проверьте: ping {host}\n"
            "  2) проект Supabase удалён или переименован — откройте панель "
            "Supabase и сверьте адрес с SUPABASE_URL в cv-service/.env\n"
            "  3) опечатка в SUPABASE_URL"
        )

    if "timed out" in text or "timeout" in text:
        return (
            f"{host} не отвечает вовремя. Связь есть, но медленная или "
            "блокируется. Проверьте, открывается ли адрес в браузере."
        )

    if "certificate" in text or "ssl" in text:
        return (
            f"Не проходит проверка сертификата {host}. Обычно это часы, "
            "сбитые на несколько лет, или перехватывающий прокси."
        )

    return f"Не удалось соединиться с {host}: {error}"


def is_network_error(error: Exception) -> bool:
    """Сеть подвела или дело в чём-то другом."""
    if error.__class__.__name__ in {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "ReadError",
        "RemoteProtocolError",
    }:
        return True
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "nodename",
            "name or service not known",
            "getaddrinfo",
            "temporary failure in name resolution",
            "connection refused",
            "connection reset",
            "timed out",
            "network is unreachable",
        )
    )


# Сколько ждать между попытками войти при обрыве связи, секунды.
#
# Растущая пауза: первое моргание проходит за секунды, а вот упавший
# роутер поднимают минутами. Долбить его каждую секунду бессмысленно.
CONNECT_RETRY_DELAYS = (2.0, 5.0, 10.0, 20.0, 30.0, 60.0)


def get_client(max_attempts: int = 0, sleep=time.sleep) -> Client:
    """
    Клиент устройства фермы.

    Устройство входит своим логином и паролем — обычным пользователем.
    Права ограничены политиками БД: писать события можно только своей ферме.
    Ключа полного доступа (secret) на ферме больше нет: если мини-ПК украдут,
    пострадает только эта ферма, а не вся база.
    """
    url = os.environ["SUPABASE_URL"]
    anon_key = os.environ["SUPABASE_ANON_KEY"]

    try:
        client = create_client(url, anon_key, options=client_options())
    except Exception as exc:
        # Набор настроек у разных версий библиотеки различается; остаться
        # без клиента из-за этого нельзя
        print(f"ограничение ожидания не задано ({exc}), работаем со стандартным")
        client = create_client(url, anon_key)

    # Ждём связь, а не умираем от первого моргания.
    #
    # На ферме интернет пропадает постоянно: мобильный канал, спутник,
    # отключения света у провайдера. Сервис, падающий от каждого такого
    # моргания, требует человека с клавиатурой — а человек за сто
    # километров. Ждать и пробовать снова правильнее.
    #
    # Неверный пароль при этом по-прежнему валит запуск сразу: сколько
    # ни жди, он не станет верным.
    attempt = 0
    while True:
        try:
            sign_in(client)
            if attempt:
                print("связь восстановлена, устройство вошло")
            return client
        except Exception as exc:
            if not is_network_error(exc):
                raise

            attempt += 1
            if max_attempts and attempt >= max_attempts:
                raise RuntimeError(
                    "Нет связи с базой.\n" + explain_connection_error(url, exc)
                ) from exc

            if attempt == 1:
                print("Нет связи с базой. " + explain_connection_error(url, exc))

            delay = CONNECT_RETRY_DELAYS[
                min(attempt - 1, len(CONNECT_RETRY_DELAYS) - 1)
            ]
            print(f"попытка {attempt} не удалась, повтор через {delay:.0f} с")
            sleep(delay)


def session_expires_in(client: Client, now: float | None = None) -> float | None:
    """Сколько секунд осталось жить токену. None, если сессии нет."""
    try:
        session = client.auth.get_session()
    except Exception:
        return None
    if session is None:
        return None

    expires_at = getattr(session, "expires_at", None)
    if not expires_at:
        return None
    moment = time.time() if now is None else now
    return float(expires_at) - moment


def ensure_session(client: Client, now: float | None = None) -> bool:
    """
    Держит сессию устройства живой.

    Без этого сервис на ферме через час превращался в тихого покойника:
    процесс работает, кадры обрабатываются, а каждая запись в базу
    отбивается по правам. Снаружи это неотличимо от «на ферме никого нет».

    Возвращает True, если пришлось что-то делать.
    """
    remaining = session_expires_in(client, now)
    if remaining is not None and remaining > SESSION_REFRESH_MARGIN_S:
        return False

    try:
        client.auth.refresh_session()
        return True
    except Exception as exc:
        print(f"обновить сессию не удалось ({exc}), вхожу заново")

    # Ключ обновления мог протухнуть за длинный обрыв связи —
    # тогда остаётся полный вход по паролю
    sign_in(client)
    return True


def get_device_farm_id(client: Client) -> str:
    """Ферма устройства берётся из его профиля, а не из настроек на месте."""
    user = client.auth.get_user()
    if not user or not user.user:
        raise RuntimeError("Сессия устройства недействительна")

    response = (
        client.table("profiles")
        .select("farm_id")
        .eq("id", user.user.id)
        .single()
        .execute()
    )
    farm_id = response.data.get("farm_id") if response.data else None
    if not farm_id:
        raise RuntimeError(
            "Устройство не привязано к ферме. Пересоздайте его в админке."
        )
    return farm_id


MINIMAL_CAMERA_FIELDS = "id, name, source_uri"
WEIGHT_CAMERA_FIELDS = f"{MINIMAL_CAMERA_FIELDS}, cm_per_pixel, placement"
FULL_CAMERA_FIELDS = f"{WEIGHT_CAMERA_FIELDS}, security_enabled, security_mode"

# Наборы полей по убыванию: пробуем сверху вниз, пока не получится.
#
# Лесенка, а не «полный набор или минимальный». Одна непринятая миграция
# не должна лишать нас всего сразу: без 0014 нет охраны, но обмер силуэта
# и расположение камеры остаются на месте. Раньше отсутствие одной колонки
# роняло запрос до минимального набора — и вместе с охраной ТИХО
# выключалась оценка веса, потому что placement приходил пустым.
CAMERA_FIELD_LADDER = [
    (FULL_CAMERA_FIELDS, None),
    (
        WEIGHT_CAMERA_FIELDS,
        "не применены миграции 0014 и 0015: тревога о постороннем работать не будет",
    ),
    (
        MINIMAL_CAMERA_FIELDS,
        "не применены миграции 0009 и 0011: оценка веса и расположение камер недоступны",
    ),
]


def fetch_cameras(client: Client, farm_id: str) -> list[dict]:
    """
    Список камер приходит с сервера, а не из файла на ферме.
    Поэтому добавление камеры в админке не требует выезда к клиенту.

    Если новые колонки ещё не заведены — работаем без них и говорим прямо,
    какой миграции не хватает. Раньше это выглядело как загадочная ошибка
    от базы, и связь с непринятой миграцией была неочевидна.
    """
    last_error: Exception | None = None

    for fields, complaint in CAMERA_FIELD_LADDER:
        try:
            response = (
                client.table("cameras")
                .select(fields)
                .eq("farm_id", farm_id)
                .execute()
            )
        except Exception as exc:
            last_error = exc
            continue

        if complaint:
            print(f"часть полей камер недоступна: {complaint}")
        return response.data or []

    raise RuntimeError(f"Не удалось прочитать список камер: {last_error}")


def fetch_zones(client: Client, camera_id: str) -> list[dict]:
    """Зоны конкретной камеры: кормушка, поилка, проход."""
    response = (
        client.table("zones")
        .select("id, name, kind, polygon")
        .eq("camera_id", camera_id)
        .execute()
    )
    return response.data or []


def fetch_animal_names(client: Client, animal_ids: list[str]) -> dict[str, str]:
    """Клички по идентификаторам — чтобы показать их на кадре."""
    if not animal_ids:
        return {}
    response = (
        client.table("animals").select("id, label").in_("id", animal_ids).execute()
    )
    return {row["id"]: row["label"] for row in (response.data or [])}


def register_camera_stream(client: Client, camera_id: str, url: str) -> bool:
    """
    Прописывает адрес видеопотока камеры.

    Возвращает False, а не роняет запуск: не прописанный адрес означает
    живой просмотр по кадру в секунду — неприятно, но работать система
    продолжает. Ронять из-за этого обработку видео было бы хуже.
    """
    try:
        client.rpc(
            "register_camera_stream",
            {"target_camera_id": camera_id, "new_url": url},
        ).execute()
        return True
    except Exception as exc:
        print(f"адрес потока не прописан: {exc}")
        return False


def send_heartbeat(client: Client) -> None:
    """Отметка «устройство живо» — по ней админка показывает статус фермы."""
    client.rpc("device_heartbeat").execute()


def insert_event_row(client: Client, row: dict) -> dict:
    """Отправка уже готовой строки — так же уходят события из локального буфера."""
    response = client.table("events").insert(row).execute()
    return response.data[0] if response.data else {}


def insert_event(client: Client, event: AnimalEvent) -> dict:
    return insert_event_row(client, event.to_row())


# Поля сеанса записи, от новых к старым — как и у камер. Не применённая
# миграция не должна выглядеть как «запись сломалась»: она должна
# называть себя
RECORDING_FIELD_LADDER = [
    (
        "id, camera_id, camera_ids, animal_id, label, captured, needed, "
        "target, per_camera, captured_by, awaiting_view",
        "",
    ),
    (
        "id, camera_id, animal_id, label, captured, needed, target, awaiting_view",
        "не применена миграция 0038: запись идёт только с одной камеры",
    ),
]

_recording_complaint_said = False


def fetch_active_recording(client: Client, camera_id: str) -> dict | None:
    """
    Идёт ли сейчас запись эталонов с участием этой камеры.

    Запрашиваем ВСЕ записи фермы, а не сразу по своей камере. Разница
    важна: если человек начал запись, не отметив эту камеру, при фильтре
    по своей мы получили бы пустоту и молчали — а он стоит перед камерой
    и ждёт, что счётчик пойдёт. Теперь такое видно и говорится вслух.

    Чужие фермы сюда не попадут: их отсекают политики доступа.
    """
    global _recording_complaint_said

    rows: list[dict] | None = None
    last_error: Exception | None = None

    for fields, complaint in RECORDING_FIELD_LADDER:
        try:
            response = (
                client.table("active_recording").select(fields).limit(5).execute()
            )
        except Exception as exc:  # noqa: BLE001 — уходит в журнал ниже
            last_error = exc
            continue

        if complaint and not _recording_complaint_said:
            _recording_complaint_said = True
            print(f"часть полей записи недоступна: {complaint}")

        rows = response.data or []
        break

    if rows is None:
        raise RuntimeError(f"Состояние записи не прочитано: {last_error}")

    if not rows:
        return None

    def participates(row: dict) -> bool:
        # Список камер — там, где миграция 0038 применена. Где нет,
        # остаётся одна камера, и сравниваем с ней
        listed = row.get("camera_ids")
        if isinstance(listed, list):
            return str(camera_id) in [str(one) for one in listed]
        return str(row.get("camera_id")) == str(camera_id)

    mine = [row for row in rows if participates(row)]
    if mine:
        return mine[0]

    # Запись идёт, но эту камеру не отметили
    return {"__other_camera__": True, "label": rows[0].get("label", "")}


def add_recording_embedding(
    client: Client,
    session_id: str,
    embedding,
    view: str | None = None,
    camera_id: str | None = None,
) -> int:
    """
    Записывает эталон.

    Возвращает набранное число. Отрицательное — брать больше не надо:
    -1 сеанс закрыт или камера не в списке, -2 квота этой камеры набрана,
    а другая камера ещё пишет.

    Закрытый сеанс — обычное дело, а не сбой: человек мог нажать
    «Отменить», пока кадр считался, или набралось нужное количество.

    `view` — какой ракурс был перед камерой. None означает «не разобрали»:
    животное поворачивалось или камера смотрит сверху, где ракурс один.
    Такой эталон всё равно годится для узнавания, просто не участвует в
    сравнении бока с боком.
    """
    payload = {
        "session_id": session_id,
        "new_embedding": list(embedding),
        "taken_view": view,
        "taken_camera_id": camera_id,
    }
    try:
        response = client.rpc("add_recording_embedding", payload).execute()
    except Exception:
        # Миграция 0038 ещё не применена: аргумента камеры в функции нет
        payload.pop("taken_camera_id")
        response = client.rpc("add_recording_embedding", payload).execute()

    try:
        return int(response.data)
    except (TypeError, ValueError):
        return -1


def fetch_health_input(client: Client, farm_id: str, days: int = 14) -> tuple:
    """
    Всё, что нужно для проверки поведения: сутки животных, сами животные
    и живость камер.

    Три запроса, а не один: сетка «животное × день» и сетка «камера ×
    день» — разные величины, и склеивать их в базе значило бы гонять по
    сети одно и то же по многу раз.
    """
    day_rows = client.rpc(
        "health_animal_days", {"target_farm_id": farm_id, "days": days}
    ).execute()
    animals = client.rpc("health_animals", {"target_farm_id": farm_id}).execute()
    cameras = client.rpc(
        "health_camera_days", {"target_farm_id": farm_id, "days": days}
    ).execute()

    return (day_rows.data or [], animals.data or [], cameras.data or [])


def apply_health_findings(client: Client, farm_id: str, findings: list) -> tuple:
    """
    Отдаёт найденное базе. Возвращает «открыто, закрыто».

    Пустой список — не пропуск, а осмысленный ответ: на ферме всё в
    порядке, и всё, что было открыто, надо закрыть. Поэтому вызывается
    даже когда находить нечего.
    """
    payload = [
        {
            "animal_id": one.animal_id,
            "kind": one.kind,
            "severity": one.severity,
            "title": one.title,
            "detail": one.detail,
            "value": one.value,
            "baseline": one.baseline,
            "days_in_row": one.days_in_row,
        }
        for one in findings
    ]

    response = client.rpc(
        "apply_health_findings",
        {"target_farm_id": farm_id, "findings": payload},
    ).execute()

    row = (response.data or [{}])[0]
    return (int(row.get("opened") or 0), int(row.get("resolved") or 0))


def add_activity(
    client: Client,
    animal_id: str,
    meters: float,
    steps: int,
    seconds: float,
) -> None:
    """Прибавляет кусок пути к суточной сводке животного."""
    client.rpc(
        "add_activity",
        {
            "target_animal_id": animal_id,
            "add_meters": round(meters, 2),
            "add_samples": steps,
            "add_seconds": round(seconds, 1),
        },
    ).execute()


def set_recording_hint(
    client: Client, session_id: str, hint: str, camera_id: str | None = None
) -> None:
    """
    Почему кадры сейчас не берутся — чтобы это увидел человек у камеры.

    Подсказка своя у каждой камеры. Общая на всех мигала бы: верхняя
    жалуется «никого не вижу», пока боковая спокойно берёт кадры, и
    человек читает жалобу как поломку. Кому её показывать, решает база:
    только если молчат все незакрытые камеры сразу.
    """
    try:
        client.rpc(
            "set_recording_hint",
            {
                "session_id": session_id,
                "camera_id": camera_id,
                "new_hint": hint,
            },
        ).execute()
    except Exception:
        # Миграция 0038 ещё не применена: подсказка была одна на сеанс
        client.rpc(
            "set_recording_hint", {"session_id": session_id, "new_hint": hint}
        ).execute()
