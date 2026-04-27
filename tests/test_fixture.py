"""Sanity: the seeded fixture DB has the expected shape."""


def test_fixture_has_eight_prs(fixture_conn):
    (n,) = fixture_conn.execute("SELECT COUNT(*) FROM pull_requests").fetchone()
    assert n == 8


def test_fixture_has_three_deployments(fixture_conn):
    (n,) = fixture_conn.execute("SELECT COUNT(*) FROM deployments").fetchone()
    assert n == 3


def test_fixture_has_both_repos(fixture_conn):
    rows = fixture_conn.execute(
        "SELECT DISTINCT repo FROM pull_requests ORDER BY repo"
    ).fetchall()
    assert rows == [("acme/api",), ("acme/web",)]
