"""Probes de Instagram y Facebook con dobles (sin navegador ni red)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from argos.browser.checkpoints import Problem
from argos.platforms.facebook import FacebookPlatform
from argos.platforms.instagram import InstagramPlatform


class FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class FakePage:
    def __init__(
        self,
        *,
        url: str = "https://www.instagram.com/",
        evaluate_result: dict[str, Any] | None = None,
        password_fields: int = 0,
    ) -> None:
        self.url = url
        self.evaluate_result = evaluate_result
        self.password_fields = password_fields
        self.visits: list[str] = []

    def title(self) -> str:
        return "Fake"

    def evaluate(self, expression: str, arg: object = None) -> object:
        return self.evaluate_result

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.password_fields)

    def wait_for_timeout(self, milliseconds: float) -> None:
        pass


@dataclass
class FakeSession:
    page: FakePage = field(default_factory=FakePage)
    jar: dict[str, str] = field(default_factory=dict)
    problem: Problem | None = None
    next_url: str | None = None

    def goto(self, url: str, **_kwargs: object) -> None:
        self.page.visits.append(url)
        self.page.url = self.next_url or url

    def cookies(self) -> dict[str, str]:
        return dict(self.jar)

    def inspect(self) -> Problem | None:
        return self.problem


def ig_success_payload() -> dict[str, Any]:
    return {
        "status": 200,
        "data": {"user": {"pk": 123, "username": "argos_test"}},
        "error": None,
    }


def test_instagram_ok_with_valid_session() -> None:
    session = FakeSession(
        page=FakePage(evaluate_result=ig_success_payload()),
        jar={"sessionid": "s", "ds_user_id": "1"},
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "ok"
    assert status.active_backend == "internal-api"
    assert "argos_test" in status.detail


def test_instagram_needs_login_without_cookies() -> None:
    session = FakeSession(
        page=FakePage(evaluate_result=ig_success_payload()), jar={}
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "needs-login"
    assert "sessionid" in (status.detail + (status.hint or ""))


def test_instagram_rate_limited_on_429() -> None:
    session = FakeSession(
        page=FakePage(evaluate_result={"status": 429, "data": None, "error": None}),
        jar={"sessionid": "s", "ds_user_id": "1"},
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "rate-limited"


def test_instagram_ui_fallback_ok_when_api_returns_html() -> None:
    """La API puede devolver 200 con algo que no decide: la UI manda."""
    session = FakeSession(
        page=FakePage(evaluate_result={"status": 200, "data": None, "error": None}),
        jar={"sessionid": "s", "ds_user_id": "1"},
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "ok"
    assert status.active_backend == "dom"
    assert "UI" in status.detail


def test_instagram_401_falls_back_to_ui_login_wall() -> None:
    session = FakeSession(
        page=FakePage(evaluate_result={"status": 401, "data": None, "error": None}),
        jar={"sessionid": "s", "ds_user_id": "1"},
        problem=Problem("login", "redirige a login"),
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "needs-login"


def test_instagram_ui_fallback_detects_login_form() -> None:
    session = FakeSession(
        page=FakePage(
            evaluate_result={"status": 200, "data": None, "error": None},
            password_fields=1,
        ),
        jar={"sessionid": "s", "ds_user_id": "1"},
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "needs-login"
    assert "formulario" in status.detail


def test_instagram_checkpoint_from_page_inspection() -> None:
    session = FakeSession(
        page=FakePage(evaluate_result=ig_success_payload()),
        jar={"sessionid": "s", "ds_user_id": "1"},
        problem=Problem("checkpoint", "URL de verificación"),
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "checkpoint"


def test_instagram_error_when_nothing_is_conclusive() -> None:
    session = FakeSession(
        page=FakePage(evaluate_result={"status": 0, "data": None, "error": "TypeError"}),
        jar={"sessionid": "s", "ds_user_id": "1"},
        next_url="https://www.instagram.com/otra-cosa/",
    )
    status = InstagramPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "error"


def test_instagram_navigates_when_told_to() -> None:
    page = FakePage(url="about:blank", evaluate_result=ig_success_payload())
    session = FakeSession(page=page, jar={"sessionid": "s", "ds_user_id": "1"})
    InstagramPlatform().probe(session, navigate=True)  # type: ignore[arg-type]
    assert page.visits


def test_facebook_ok_verified_in_me() -> None:
    session = FakeSession(
        page=FakePage(url="https://www.facebook.com/me"),
        jar={"c_user": "1", "xs": "x"},
    )
    status = FacebookPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "ok"
    assert "verificada" in status.detail
    assert status.active_backend == "dom"


def test_facebook_needs_login_without_cookies() -> None:
    session = FakeSession(jar={"c_user": "1"})
    status = FacebookPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "needs-login"
    assert "xs" in status.detail


def test_facebook_needs_login_when_login_form_present() -> None:
    session = FakeSession(
        page=FakePage(url="https://www.facebook.com/login", password_fields=1),
        jar={"c_user": "1", "xs": "x"},
    )
    status = FacebookPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "needs-login"


def test_facebook_checkpoint_wins() -> None:
    session = FakeSession(
        page=FakePage(url="https://www.facebook.com/checkpoint/1"),
        jar={"c_user": "1", "xs": "x"},
        problem=Problem("checkpoint", "URL de verificación"),
    )
    status = FacebookPlatform().probe(session)  # type: ignore[arg-type]
    assert status.status == "checkpoint"


def test_facebook_non_navigating_probe_reports_cookie_state() -> None:
    session = FakeSession(
        page=FakePage(url="https://www.facebook.com/"),
        jar={"c_user": "1", "xs": "x"},
    )
    status = FacebookPlatform().probe(session, navigate=False)  # type: ignore[arg-type]
    assert status.status == "ok"
    assert "cookies" in status.detail
