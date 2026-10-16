from core import ivg_dbx


def test_read_commands_pass_and_write_commands_are_refused():
    assert ivg_dbx.check(["jobs"]) is None
    assert ivg_dbx.check(["--env", "prod", "run-status", "123"]) is None
    for args in (["run-job", "1"], ["import", "a", "b"], ["run-notebook", "/x"], ["pull"], [], ["--env", "dev", "jobs"]):
        assert ivg_dbx.check(args)


def test_sql_must_be_single_read_only_statement():
    assert ivg_dbx.check(["sql", "SELECT 1", "--limit", "5"]) is None
    assert ivg_dbx.check(["--env", "prod", "sql", "--limit=5", "SHOW TABLES"]) is None
    assert ivg_dbx.check(["sql", "DELETE FROM t"])
    assert ivg_dbx.check(["sql", "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x"])
    assert ivg_dbx.check(["sql", "SELECT 1; DROP TABLE t"])
    assert ivg_dbx.check(["sql", "SELECT 1", "--csv", "out.csv"])


def test_option_with_equals_cannot_smuggle_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ivg_dbx, "IVG_ROOT", tmp_path)
    (tmp_path / "evil.sql").write_text("DROP TABLE t", encoding="utf-8")
    (tmp_path / "ok.sql").write_text("SELECT 1", encoding="utf-8")
    assert ivg_dbx.check(["sql", "SELECT 1", "--file=evil.sql"])
    assert ivg_dbx.check(["sql", "SELECT 1", "--fi", "evil.sql"])
    assert ivg_dbx.check(["sql", "SELECT 1", "--cs", "out.csv"])
    assert ivg_dbx.check(["sql", "--file", "ok.sql"]) is None
    assert ivg_dbx.check(["sql", "--file", "../outside.sql"])


def test_main_refuses_without_running_dbx(monkeypatch):
    monkeypatch.setattr(ivg_dbx.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert ivg_dbx.main(["run-job", "1"]) == 2
