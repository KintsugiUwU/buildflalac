from conftest import default_tags, make_flac
from starlette.testclient import TestClient

from flalac.web import create_app


def test_library_status_log_and_health(workspace, make_engine):
    source, _, _ = workspace
    make_flac(source / "Artist/Album/01 Song.flac", tags=default_tags("Song"))
    engine = make_engine()
    engine.run_pass()
    client = TestClient(create_app(engine))
    page = client.get("/")
    assert page.status_code == 200
    assert "Artist/Album" in page.text and "01 Song" in page.text
    assert "1 of 1" in client.get("/status").text
    assert "encoded" in client.get("/log").text
    assert client.get("/health").json()["ok"] is True
    assert client.get("/api/status").json()["synced"] == 1
    assert "Nothing matches" in client.get("/?view=problems", headers={"hx-request": "1"}).text


def test_token_gate(workspace, make_engine):
    engine = make_engine(auth_token="s3cret")
    client = TestClient(create_app(engine))
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/api/status").status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/api/status", headers={"authorization": "Bearer s3cret"}).status_code == 200
    bad = client.post("/login", data={"token": "nope"})
    assert "doesn't match" in bad.text
    client.post("/login", data={"token": "s3cret"})
    assert client.get("/").status_code == 200


def test_lyrics_style_switch(workspace, make_engine):
    engine = make_engine()
    client = TestClient(create_app(engine))
    assert 'value="plain" checked' in client.get("/").text
    client.post("/lyrics-style", data={"style": "synced"})
    assert engine.lyrics_style == "synced"
    assert 'value="synced" checked' in client.get("/").text
    client.post("/lyrics-style", data={"style": "nonsense"})
    assert engine.lyrics_style == "synced"


def test_mac_page_script_and_sync(workspace, make_engine):
    engine = make_engine()
    client = TestClient(create_app(engine), base_url="http://nas:8090")
    assert "flalac for Mac" in client.get("/mac").text
    script = client.get("/mac/script")
    assert 'property serverURL : "http://nas:8090"' in script.text
    assert "attachment" in script.headers["content-disposition"]
    answer = client.post("/api/mac-sync", content="mac\tMacBook\nroot\t/Volumes/x/ALAC\n")
    assert answer.status_code == 200 and answer.text == "\n"
    assert client.post("/api/mac-sync", content="track\tP1\t0\t/x").status_code == 400
    assert "MacBook" in client.get("/mac").text


def test_cross_site_posts_are_refused(workspace, make_engine):
    engine = make_engine()
    client = TestClient(create_app(engine))
    evil = client.post("/deletes/confirm", headers={"origin": "https://evil.example"})
    assert evil.status_code == 403
    assert engine._confirm_deletes is False
    own = client.post(
        "/deletes/confirm", data={"count": "4"}, headers={"origin": "http://testserver"}
    )
    assert own.status_code in (200, 303)
    assert (engine._confirm_deletes, engine._confirm_count) == (True, 4)


def test_the_mac_script_carries_the_token(workspace, make_engine):
    client = TestClient(create_app(make_engine(auth_token='s3"cret')))
    script = client.get("/mac/script", headers={"authorization": 'Bearer s3"cret'}).text
    assert 'property authToken : "s3\\"cret"' in script
    open_script = TestClient(create_app(make_engine())).get("/mac/script").text
    assert 'property authToken : ""' in open_script


def test_version_is_the_same_everywhere():
    import tomllib
    from pathlib import Path

    from flalac import __version__

    project = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    assert project["project"]["version"] == __version__
