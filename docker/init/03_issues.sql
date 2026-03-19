-- Issues & issue threads for admin-agent collaboration
--
-- Workflow:
--   1. Admin creates an issue (bug report or feature request)
--   2. Agent cron picks it up, asks clarifying questions via thread messages
--   3. Admin replies in thread
--   4. Agent proposes a plan (status → 'planning')
--   5. Admin approves plan (status → 'approved')
--   6. Agent works on it (status → 'in_progress')
--   7. Agent marks done (status → 'done')

CREATE TABLE IF NOT EXISTS issues (
    id          SERIAL PRIMARY KEY,
    title       VARCHAR(256)  NOT NULL,
    description TEXT          NOT NULL DEFAULT '',
    type        VARCHAR(32)   NOT NULL DEFAULT 'bug',     -- 'bug' | 'feature'
    priority    VARCHAR(16)   NOT NULL DEFAULT 'medium',  -- 'low' | 'medium' | 'high' | 'urgent'
    status      VARCHAR(32)   NOT NULL DEFAULT 'open',    -- 'open' | 'planning' | 'approved' | 'in_progress' | 'done' | 'closed'
    created_by  VARCHAR(128)  NOT NULL DEFAULT '',        -- admin name
    assignee    VARCHAR(128)  NOT NULL DEFAULT 'agent',   -- 'agent' or admin name
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS issue_messages (
    id          SERIAL PRIMARY KEY,
    issue_id    INTEGER       NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    sender      VARCHAR(128)  NOT NULL,                   -- 'agent' or admin name
    role        VARCHAR(16)   NOT NULL DEFAULT 'user',    -- 'user' | 'agent'
    content     TEXT          NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_issue_messages_issue_id ON issue_messages(issue_id);
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
