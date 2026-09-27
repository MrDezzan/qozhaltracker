from unittest.mock import MagicMock, patch

import pytest

from cv_service.events import AnimalEvent
from types import SimpleNamespace

from cv_service.supabase_client import (
    WEIGHT_CAMERA_FIELDS,
    fetch_cameras,
    get_client,
    get_device_farm_id,
    insert_event,
    send_heartbeat,
)


def test_insert_event_calls_table_events_insert():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.data = [{"id": "abc", "event_type": "detected"}]
    fake_client.table.return_value.insert.return_value.execute.return_value = fake_response

    event = AnimalEvent(
        farm_id="11111111-1111-1111-1111-111111111111",
        camera_id="22222222-2222-2222-2222-222222222222",
        event_type="detected",
        payload={"track_id": 3},
    )
    result = insert_event(fake_client, event)

    fake_client.table.assert_called_once_with("events")
    inserted_row = fake_client.table.return_value.insert.call_args[0][0]
    assert inserted_row["event_type"] == "detected"
    assert inserted_row["payload"]["track_id"] == 3
    assert result["id"] == "abc"


@patch.dict(
    "os.environ",
    {
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_ANON_KEY": "anon-key",
        "DEVICE_LOGIN": "device-abc@livestock.local",
        "DEVICE_PASSWORD": "secret",
    },
    clear=True,
)
@patch("cv_service.supabase_client.create_client")
def test_get_client_signs_in_with_device_credentials(mock_create):
    fake_client = MagicMock()
    fake_client.auth.sign_in_with_password.return_value = MagicMock(session=MagicMock())
    mock_create.return_value = fake_client

    client = get_client()

    # Ключ полного доступа не используется — только публичный anon-ключ
    assert mock_create.call_args[0][1] == "anon-key"
    fake_client.auth.sign_in_with_password.assert_called_once_with(
        {"email": "device-abc@livestock.local", "password": "secret"}
    )
    assert client is fake_client


@patch.dict(
    "os.environ",
    {
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_ANON_KEY": "anon-key",
        "DEVICE_LOGIN": "device-abc@livestock.local",
        "DEVICE_PASSWORD": "wrong",
    },
    clear=True,
)
@patch("cv_service.supabase_client.create_client")
def test_get_client_raises_on_bad_credentials(mock_create):
    fake_client = MagicMock()
    fake_client.auth.sign_in_with_password.return_value = MagicMock(session=None)
    mock_create.return_value = fake_client

    with pytest.raises(RuntimeError, match="DEVICE_LOGIN"):
        get_client()


def test_get_device_farm_id_reads_profile():
    fake_client = MagicMock()
    fake_client.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-1"))
    chain = fake_client.table.return_value.select.return_value.eq.return_value.single.return_value
    chain.execute.return_value = MagicMock(data={"farm_id": "farm-1"})

    assert get_device_farm_id(fake_client) == "farm-1"
    fake_client.table.assert_called_once_with("profiles")


def test_get_device_farm_id_raises_when_not_bound():
    fake_client = MagicMock()
    fake_client.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-1"))
    chain = fake_client.table.return_value.select.return_value.eq.return_value.single.return_value
    chain.execute.return_value = MagicMock(data={"farm_id": None})

    with pytest.raises(RuntimeError, match="не привязано к ферме"):
        get_device_farm_id(fake_client)


def test_fetch_cameras_filters_by_farm():
    fake_client = MagicMock()
    chain = fake_client.table.return_value.select.return_value.eq.return_value
    chain.execute.return_value = MagicMock(
        data=[{"id": "cam-1", "name": "Кормушка", "source_uri": "rtsp://x"}]
    )

    cameras = fetch_cameras(fake_client, "farm-1")

    fake_client.table.assert_called_once_with("cameras")
    fake_client.table.return_value.select.return_value.eq.assert_called_once_with(
        "farm_id", "farm-1"
    )
    assert cameras[0]["name"] == "Кормушка"


class TestCameraFieldLadder:
    """
    Непринятая миграция не должна отнимать больше, чем должна.

    Раньше отсутствие одной новой колонки роняло запрос сразу до
    минимального набора — и вместе с новой возможностью ТИХО выключалась
    оценка веса, потому что placement приходил пустым. Связь между
    «не применил 0014» и «пропали килограммы» не нашёл бы никто.
    """

    def _client_rejecting(self, forbidden: str):
        """Клиент, который отказывает любому запросу с этим полем."""
        attempts: list[str] = []

        class Table:
            def select(self, fields):
                attempts.append(fields)
                if forbidden in fields:
                    raise RuntimeError(f'column "{forbidden}" does not exist')
                return self

            def eq(self, *_args):
                return self

            def execute(self):
                return SimpleNamespace(data=[{"id": "cam-1", "name": "Загон"}])

        client = SimpleNamespace(table=lambda _name: Table())
        return client, attempts

    def test_missing_security_column_keeps_weight_fields(self):
        client, attempts = self._client_rejecting("security_enabled")

        fetch_cameras(client, "farm-1")

        assert "placement" in attempts[-1]
        assert "cm_per_pixel" in attempts[-1]

    def test_falls_all_the_way_down_when_nothing_new_exists(self):
        client, attempts = self._client_rejecting("cm_per_pixel")

        cameras = fetch_cameras(client, "farm-1")

        assert attempts[-1] == "id, name, source_uri"
        assert cameras[0]["id"] == "cam-1"

    def test_a_completely_broken_table_raises_instead_of_lying(self):
        client, _ = self._client_rejecting("id")

        with pytest.raises(RuntimeError):
            fetch_cameras(client, "farm-1")


def test_fetch_cameras_returns_empty_list_when_none():
    fake_client = MagicMock()
    chain = fake_client.table.return_value.select.return_value.eq.return_value
    chain.execute.return_value = MagicMock(data=None)

    assert fetch_cameras(fake_client, "farm-1") == []


def test_send_heartbeat_calls_rpc():
    fake_client = MagicMock()
    send_heartbeat(fake_client)
    fake_client.rpc.assert_called_once_with("device_heartbeat")


def test_fetch_animal_names_returns_a_map():
    from cv_service.supabase_client import fetch_animal_names

    client = MagicMock()
    chain = client.table.return_value.select.return_value.in_.return_value
    chain.execute.return_value = MagicMock(
        data=[{"id": "a1", "label": "Зорька"}, {"id": "a2", "label": "Бурёнка"}]
    )

    names = fetch_animal_names(client, ["a1", "a2"])

    assert names == {"a1": "Зорька", "a2": "Бурёнка"}
    client.table.assert_called_once_with("animals")


def test_fetch_animal_names_skips_the_query_when_nothing_asked():
    from cv_service.supabase_client import fetch_animal_names

    client = MagicMock()
    assert fetch_animal_names(client, []) == {}
    client.table.assert_not_called()


# ---------------------------------------------------------------------------
# Жизнь сессии устройства
# ---------------------------------------------------------------------------

from cv_service.supabase_client import ensure_session, session_expires_in, sign_in


def _client_with_session(expires_at):
    client = MagicMock()
    session = MagicMock()
    session.expires_at = expires_at
    client.auth.get_session.return_value = session
    return client


class TestSession:
    def test_reports_how_long_the_token_lives(self):
        client = _client_with_session(1000)
        assert session_expires_in(client, now=400) == 600

    def test_no_session_means_unknown(self):
        client = MagicMock()
        client.auth.get_session.return_value = None
        assert session_expires_in(client) is None

    def test_a_fresh_token_is_left_alone(self):
        client = _client_with_session(10_000)
        assert ensure_session(client, now=0) is False
        client.auth.refresh_session.assert_not_called()

    def test_an_expiring_token_is_refreshed(self):
        """
        Без этого сервис через час превращался в тихого покойника: процесс
        работает, кадры идут, а каждая запись отбивается по правам.
        """
        client = _client_with_session(100)
        assert ensure_session(client, now=0) is True
        client.auth.refresh_session.assert_called_once()

    def test_a_dead_refresh_token_falls_back_to_a_full_login(self):
        """Ключ обновления мог протухнуть за длинный обрыв связи."""
        client = _client_with_session(0)
        client.auth.refresh_session.side_effect = Exception("refresh token expired")

        with patch.dict(
            "os.environ", {"DEVICE_LOGIN": "d@f.kz", "DEVICE_PASSWORD": "x"}, clear=True
        ):
            assert ensure_session(client, now=0) is True

        client.auth.sign_in_with_password.assert_called_once()

    def test_a_broken_client_does_not_explode(self):
        client = MagicMock()
        client.auth.get_session.side_effect = Exception("нет сети")
        client.auth.refresh_session.return_value = MagicMock()
        assert ensure_session(client, now=0) is True

    def test_sign_in_rejects_bad_credentials(self):
        client = MagicMock()
        client.auth.sign_in_with_password.return_value = MagicMock(session=None)
        with patch.dict(
            "os.environ", {"DEVICE_LOGIN": "d@f.kz", "DEVICE_PASSWORD": "x"}, clear=True
        ):
            with pytest.raises(RuntimeError, match="учётной записью устройства"):
                sign_in(client)


# ---------------------------------------------------------------------------
# Камеры при непринятых миграциях
# ---------------------------------------------------------------------------

from cv_service.supabase_client import FULL_CAMERA_FIELDS, MINIMAL_CAMERA_FIELDS


class TestFetchCamerasFallback:
    def _client(self, fail_on_full: bool):
        client = MagicMock()
        calls = []

        def select(fields):
            calls.append(fields)
            chain = MagicMock()
            if fail_on_full and fields == FULL_CAMERA_FIELDS:
                chain.eq.return_value.execute.side_effect = Exception(
                    'column cameras.placement does not exist'
                )
            else:
                chain.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "cam-1", "name": "Кормушка", "source_uri": "0"}]
                )
            return chain

        client.table.return_value.select.side_effect = select
        return client, calls

    def test_takes_the_full_set_when_migrations_are_applied(self):
        client, calls = self._client(fail_on_full=False)
        assert fetch_cameras(client, "farm-1")
        assert calls == [FULL_CAMERA_FIELDS]

    def test_falls_back_and_keeps_working(self):
        """
        Раньше непринятая миграция роняла весь сервис загадочной ошибкой
        от базы, и связь с миграцией была неочевидна.
        """
        client, calls = self._client(fail_on_full=True)
        cameras = fetch_cameras(client, "farm-1")

        assert len(cameras) == 1
        # Спускаемся по одной ступени, а не сразу вниз
        assert calls[0] == FULL_CAMERA_FIELDS
        assert calls[1] == WEIGHT_CAMERA_FIELDS

    def test_the_fallback_says_what_to_do(self, capsys):
        client, _ = self._client(fail_on_full=True)
        fetch_cameras(client, "farm-1")
        assert "миграци" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Ограничение ожидания
# ---------------------------------------------------------------------------

from cv_service.supabase_client import REQUEST_TIMEOUT_S, client_options


def test_request_timeout_is_set_and_reasonable():
    """
    Без потолка зависший запрос держит поток вечно. На ферме связь рвётся
    так, что соединение не закрывается, а перестаёт отвечать.
    """
    assert 3 <= REQUEST_TIMEOUT_S <= 30
    assert client_options().postgrest_client_timeout == REQUEST_TIMEOUT_S


def test_client_survives_unsupported_options():
    """Набор настроек у версий библиотеки разный — остаться без клиента нельзя."""
    env = {
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_ANON_KEY": "k",
        "DEVICE_LOGIN": "d@f.kz",
        "DEVICE_PASSWORD": "p",
    }
    created = MagicMock()
    created.auth.sign_in_with_password.return_value = MagicMock(session=MagicMock())

    def create(url, key, options=None):
        if options is not None:
            raise TypeError("unexpected keyword")
        return created

    with patch.dict("os.environ", env, clear=True):
        with patch("cv_service.supabase_client.create_client", side_effect=create):
            assert get_client() is created


class TestConnectionErrors:
    """
    Сетевую ошибку надо объяснять словами.

    Сырой стек httpx на пятнадцать строк заканчивается фразой
    «nodename nor servname provided». По ней невозможно догадаться, что
    делать, — а делать надо разное: при отсутствии интернета ждать, при
    удалённом проекте заводить новый.
    """

    URL = "https://abc123.supabase.co"

    def test_dns_failure_names_all_three_causes(self):
        from cv_service.supabase_client import explain_connection_error

        text = explain_connection_error(
            self.URL, OSError("[Errno 8] nodename nor servname provided, or not known")
        )

        assert "abc123.supabase.co" in text
        assert "интернет" in text.lower()
        assert "supabase" in text.lower()
        assert "SUPABASE_URL" in text

    def test_linux_wording_is_recognised_too(self):
        from cv_service.supabase_client import explain_connection_error

        # На мини-ПК фермы Linux, и текст ошибки там другой
        text = explain_connection_error(self.URL, OSError("Name or service not known"))
        assert "не разрешается" in text

    def test_timeout_is_not_confused_with_dns(self):
        from cv_service.supabase_client import explain_connection_error

        text = explain_connection_error(self.URL, TimeoutError("connection timed out"))
        assert "не отвечает вовремя" in text

    def test_clock_problem_is_named(self):
        from cv_service.supabase_client import explain_connection_error

        text = explain_connection_error(
            self.URL, OSError("certificate verify failed: certificate has expired")
        )
        assert "часы" in text

    def test_unknown_error_still_says_something_useful(self):
        from cv_service.supabase_client import explain_connection_error

        text = explain_connection_error(self.URL, OSError("что-то новое"))
        assert "abc123.supabase.co" in text
        assert "что-то новое" in text


class TestWaitingForNetwork:
    """
    Моргание связи не должно ронять сервис.

    На ферме интернет пропадает постоянно: мобильный канал, спутник,
    отключения у провайдера. Сервис, падающий от каждого моргания,
    требует человека с клавиатурой — а человек за сто километров.
    """

    ENV = {
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_ANON_KEY": "anon-key",
        "DEVICE_LOGIN": "device-abc@livestock.local",
        "DEVICE_PASSWORD": "secret",
    }

    def _client(self, failures: int):
        """Клиент, который отказывает по сети N раз, потом входит."""
        client = MagicMock()
        calls = {"n": 0}

        def sign_in(_credentials):
            calls["n"] += 1
            if calls["n"] <= failures:
                raise OSError("[Errno 8] nodename nor servname provided")
            return MagicMock(session=MagicMock())

        client.auth.sign_in_with_password.side_effect = sign_in
        return client

    @patch.dict("os.environ", ENV, clear=True)
    @patch("cv_service.supabase_client.create_client")
    def test_waits_out_a_blip_and_connects(self, mock_create):
        from cv_service.supabase_client import get_client

        mock_create.return_value = self._client(failures=3)
        slept: list[float] = []

        client = get_client(sleep=slept.append)

        assert client is mock_create.return_value
        assert len(slept) == 3

    @patch.dict("os.environ", ENV, clear=True)
    @patch("cv_service.supabase_client.create_client")
    def test_the_pause_grows(self, mock_create):
        """
        Первое моргание проходит за секунды, а упавший роутер поднимают
        минутами. Долбить его каждую секунду бессмысленно.
        """
        from cv_service.supabase_client import get_client

        mock_create.return_value = self._client(failures=4)
        slept: list[float] = []
        get_client(sleep=slept.append)

        assert slept == sorted(slept)
        assert slept[-1] > slept[0]

    @patch.dict("os.environ", ENV, clear=True)
    @patch("cv_service.supabase_client.create_client")
    def test_a_wrong_password_fails_immediately(self, mock_create):
        """Сколько ни жди, пароль верным не станет."""
        from cv_service.supabase_client import get_client

        client = MagicMock()
        client.auth.sign_in_with_password.return_value = MagicMock(session=None)
        mock_create.return_value = client

        slept: list[float] = []
        with pytest.raises(RuntimeError, match="DEVICE_LOGIN"):
            get_client(sleep=slept.append)

        assert slept == []

    @patch.dict("os.environ", ENV, clear=True)
    @patch("cv_service.supabase_client.create_client")
    def test_gives_up_when_asked_to(self, mock_create):
        """В тестах и проверках бесконечное ожидание недопустимо."""
        from cv_service.supabase_client import get_client

        mock_create.return_value = self._client(failures=99)

        with pytest.raises(RuntimeError, match="Нет связи"):
            get_client(max_attempts=3, sleep=lambda _s: None)


class TestIsNetworkError:
    def test_dns_counts(self):
        from cv_service.supabase_client import is_network_error

        assert is_network_error(OSError("nodename nor servname provided"))
        assert is_network_error(OSError("Temporary failure in name resolution"))

    def test_refusal_and_reset_count(self):
        from cv_service.supabase_client import is_network_error

        assert is_network_error(OSError("Connection refused"))
        assert is_network_error(OSError("Connection reset by peer"))

    def test_a_wrong_password_is_not_a_network_error(self):
        from cv_service.supabase_client import is_network_error

        assert not is_network_error(RuntimeError("Проверьте DEVICE_LOGIN"))

    def test_a_missing_table_is_not_a_network_error(self):
        from cv_service.supabase_client import is_network_error

        assert not is_network_error(RuntimeError('relation "animals" does not exist'))
