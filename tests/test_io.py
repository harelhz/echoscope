import json
from datetime import datetime, timezone

from typer.testing import CliRunner

from echoscope.cli import app
from echoscope.collectors.jsonl import read_jsonl, write_jsonl
from echoscope.demo import build_scenario
from echoscope.models import Post
from echoscope.storage import Store


def test_store_is_idempotent(tmp_path):
    post = Post("telegram", "chan", "5", datetime(2026, 1, 1, tzinfo=timezone.utc), "hello")
    with Store(tmp_path / "t.db") as store:
        store.add([post])
        store.add([post])
        assert store.stats() == {"posts": 1, "channels": 1}
        assert store.last_message_id("telegram", "chan") == 5
        assert store.posts()[0].text == "hello"


def test_jsonl_roundtrip(tmp_path):
    posts = build_scenario(1).posts[:50]
    path = tmp_path / "posts.jsonl"
    write_jsonl(posts, path)
    back = list(read_jsonl(path))
    assert [p.key for p in back] == [p.key for p in posts]
    assert back[0].timestamp == posts[0].timestamp


def test_cli_import_and_detect(tmp_path):
    data, db = tmp_path / "posts.jsonl", tmp_path / "e.db"
    write_jsonl(build_scenario(3).posts, data)
    runner = CliRunner()
    assert runner.invoke(app, ["import", str(data), "--db", str(db)]).exit_code == 0
    out_json, out_html = tmp_path / "r.json", tmp_path / "r.html"
    result = runner.invoke(app, ["detect", "--db", str(db), "--json", str(out_json),
                                 "--html", str(out_html), "--details", "0"])
    assert result.exit_code == 0, result.output
    report = json.loads(out_json.read_text())
    assert sum(c["confidence"] != "LOW" for c in report["campaigns"]) == 8
    assert "<svg" in out_html.read_text()
