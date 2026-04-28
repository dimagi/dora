-- Seed fixture for metric tests.
--
-- Three weeks of activity across two repos:
--   W42 (2025-10-13 Mon): acme/api  — 3 merged PRs, 1 caused-incident,
--                                     2 deployments (1 success, 1 failure)
--   W43 (2025-10-20 Mon): acme/api  — 2 merged PRs, 0 caused-incident,
--                                     1 deployment (inactive = succeeded-then-superseded)
--                         acme/web  — 1 merged PR (hotfix), 0 deployments
--   W44 (2025-10-27 Mon): acme/api  — 1 merged PR (no first_commit_at), 0 deployments
--
-- Lead-time values (merged_at - first_commit_at in hours):
--   PR 1: 10h, PR 2: 20h, PR 3: 30h, PR 4: 5h, PR 5: 15h, PR 6: 1h, PR 7: NULL
-- Median for W42 = 20h, for W43 on acme/api = 10h, acme/web = 1h.
--
-- review-latency values (merged_at - COALESCE(ready_for_review_at, opened_at) in hours):
--   PR 1: changed_files=1  → bucket XS, 34h
--   PR 2: changed_files=3  → bucket S,  34h  (ready_for_review_at = opened+10h, draft case)
--   PR 3: changed_files=7  → bucket M,  30h
--   PR 4: changed_files=1  → bucket XS, 5h
--   PR 5: changed_files=25 → bucket L+, 15h
--   PR 6: changed_files=2  → bucket S,  1h
--   PR 7: changed_files=NULL → excluded from metric

CREATE TABLE IF NOT EXISTS pull_requests (
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT,
    author TEXT,
    base TEXT,
    opened_at TEXT NOT NULL,
    merged_at TEXT,
    first_commit_at TEXT,
    merge_sha TEXT,
    labels TEXT,
    additions INTEGER,
    deletions INTEGER,
    changed_files INTEGER,
    ready_for_review_at TEXT,
    PRIMARY KEY (repo, number)
);

CREATE TABLE IF NOT EXISTS deployments (
    repo TEXT NOT NULL,
    deployment_id INTEGER NOT NULL,
    sha TEXT NOT NULL,
    environment TEXT,
    created_at TEXT NOT NULL,
    status TEXT,
    PRIMARY KEY (repo, deployment_id)
);

CREATE INDEX IF NOT EXISTS idx_pr_merged   ON pull_requests(repo, merged_at);
CREATE INDEX IF NOT EXISTS idx_dep_created ON deployments(repo, created_at);

-- W42: acme/api, 3 merged PRs
INSERT INTO pull_requests VALUES
    ('acme/api', 1, 'PR 1', 'alice', 'main',
     '2025-10-13T00:00:00Z', '2025-10-14T10:00:00Z', '2025-10-14T00:00:00Z',
     'sha1', '',
     30, 5, 1, NULL),
    ('acme/api', 2, 'PR 2', 'bob',   'main',
     '2025-10-14T00:00:00Z', '2025-10-15T20:00:00Z', '2025-10-15T00:00:00Z',
     'sha2', 'caused-incident',
     120, 40, 3, '2025-10-14T10:00:00Z'),
    ('acme/api', 3, 'PR 3', 'carol', 'main',
     '2025-10-15T00:00:00Z', '2025-10-16T06:00:00Z', '2025-10-15T00:00:00Z',
     'sha3', '',
     200, 80, 7, NULL);

-- W42: acme/api deployments (1 success, 1 failure)
INSERT INTO deployments VALUES
    ('acme/api', 100, 'sha1', 'production', '2025-10-14T11:00:00Z', 'success'),
    ('acme/api', 101, 'sha2', 'production', '2025-10-15T21:00:00Z', 'failure');

-- W43: acme/api, 2 merged PRs
INSERT INTO pull_requests VALUES
    ('acme/api', 4, 'PR 4', 'alice', 'main',
     '2025-10-20T00:00:00Z', '2025-10-20T05:00:00Z', '2025-10-20T00:00:00Z',
     'sha4', '',
     15, 2, 1, NULL),
    ('acme/api', 5, 'PR 5', 'dave',  'main',
     '2025-10-21T00:00:00Z', '2025-10-21T15:00:00Z', '2025-10-21T00:00:00Z',
     'sha5', '',
     900, 200, 25, NULL);

-- W43: acme/api deployment (inactive = auto-superseded)
INSERT INTO deployments VALUES
    ('acme/api', 102, 'sha4', 'production', '2025-10-20T06:00:00Z', 'inactive');

-- W43: acme/web, 1 merged PR (hotfix)
INSERT INTO pull_requests VALUES
    ('acme/web', 6, 'PR 6 hotfix', 'alice', 'main',
     '2025-10-22T00:00:00Z', '2025-10-22T01:00:00Z', '2025-10-22T00:00:00Z',
     'sha6', 'hotfix',
     20, 5, 2, NULL);

-- W44: acme/api, 1 merged PR without first_commit_at (lead-time excluded)
-- Also no changed_files → review-latency excluded.
INSERT INTO pull_requests VALUES
    ('acme/api', 7, 'PR 7', 'alice', 'main',
     '2025-10-27T00:00:00Z', '2025-10-28T00:00:00Z', NULL,
     'sha7', '',
     NULL, NULL, NULL, NULL);

-- W42 (Sun 2025-10-26 — last day of W42 by SQLite %W, Mon-start):
-- acme/api, 1 merged PR authored by dependabot (bot author).
-- Used to verify the bot-filter behavior across metrics.
-- changed_files=15 → would be a "large PR"; weekend merge.
-- Both metrics exclude bots by default, so it should be invisible to them;
-- deploy-freq-prs / change-failure-rate include bots so it should appear there.
INSERT INTO pull_requests VALUES
    ('acme/api', 8, 'chore(deps): bump cryptography', 'dependabot[bot]', 'main',
     '2025-10-26T00:00:00Z', '2025-10-26T00:30:00Z', '2025-10-26T00:00:00Z',
     'sha8', '',
     200, 100, 15, NULL);
