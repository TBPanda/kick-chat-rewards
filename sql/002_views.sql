-- Activity views for rewards / reporting (Postgres)

CREATE OR REPLACE VIEW activity_daily AS
SELECT
    channel_slug,
    kick_user_id,
    username,
    (DATE_TRUNC('day', created_at))::DATE AS activity_date,
    COUNT(*) AS message_count,
    COUNT(*) FILTER (WHERE NOT COALESCE(is_command, FALSE)) AS non_command_message_count,
    MIN(created_at) AS first_message_at,
    MAX(created_at) AS last_message_at
FROM chat_messages
GROUP BY 1, 2, 3, 4;

CREATE OR REPLACE VIEW leaderboard_all_time AS
SELECT
    channel_slug,
    kick_user_id,
    MAX(username) AS username,
    COUNT(*) AS message_count,
    COUNT(DISTINCT (DATE_TRUNC('day', created_at))::DATE) AS active_days,
    MIN(created_at) AS first_message_at,
    MAX(created_at) AS last_message_at
FROM chat_messages
WHERE NOT COALESCE(is_command, FALSE)
GROUP BY channel_slug, kick_user_id
ORDER BY channel_slug, message_count DESC;

CREATE OR REPLACE VIEW leaderboard_7d AS
SELECT
    channel_slug,
    kick_user_id,
    MAX(username) AS username,
    COUNT(*) AS message_count,
    COUNT(DISTINCT (DATE_TRUNC('day', created_at))::DATE) AS active_days,
    MIN(created_at) AS first_message_at,
    MAX(created_at) AS last_message_at
FROM chat_messages
WHERE NOT COALESCE(is_command, FALSE)
  AND created_at >= NOW() - INTERVAL '7 days'
GROUP BY channel_slug, kick_user_id
ORDER BY channel_slug, message_count DESC;

CREATE OR REPLACE VIEW leaderboard_30d AS
SELECT
    channel_slug,
    kick_user_id,
    MAX(username) AS username,
    COUNT(*) AS message_count,
    COUNT(DISTINCT (DATE_TRUNC('day', created_at))::DATE) AS active_days,
    MIN(created_at) AS first_message_at,
    MAX(created_at) AS last_message_at
FROM chat_messages
WHERE NOT COALESCE(is_command, FALSE)
  AND created_at >= NOW() - INTERVAL '30 days'
GROUP BY channel_slug, kick_user_id
ORDER BY channel_slug, message_count DESC;

CREATE OR REPLACE VIEW user_channel_activity AS
SELECT
    kick_user_id,
    MAX(username) AS username,
    channel_slug,
    COUNT(*) AS message_count,
    COUNT(DISTINCT (DATE_TRUNC('day', created_at))::DATE) AS active_days,
    MIN(created_at) AS first_message_at,
    MAX(created_at) AS last_message_at
FROM chat_messages
WHERE NOT COALESCE(is_command, FALSE)
GROUP BY kick_user_id, channel_slug
ORDER BY kick_user_id, message_count DESC;

CREATE OR REPLACE VIEW user_cross_channel_summary AS
SELECT
    kick_user_id,
    MAX(username) AS username,
    COUNT(DISTINCT channel_slug) AS channel_count,
    COUNT(*) AS total_message_count,
    COUNT(DISTINCT (DATE_TRUNC('day', created_at))::DATE) AS active_days,
    MIN(created_at) AS first_message_at,
    MAX(created_at) AS last_message_at
FROM chat_messages
WHERE NOT COALESCE(is_command, FALSE)
GROUP BY kick_user_id
ORDER BY total_message_count DESC;

CREATE OR REPLACE VIEW activity_by_stream AS
SELECT
    s.channel_slug,
    s.session_id,
    s.title AS stream_title,
    s.started_at,
    s.ended_at,
    m.kick_user_id,
    m.username,
    COUNT(*) AS message_count
FROM stream_sessions s
JOIN chat_messages m
  ON m.channel_slug = s.channel_slug
 AND m.created_at >= s.started_at
 AND (s.ended_at IS NULL OR m.created_at <= s.ended_at)
WHERE NOT COALESCE(m.is_command, FALSE)
GROUP BY 1, 2, 3, 4, 5, 6, 7;

CREATE OR REPLACE VIEW stream_active_days AS
SELECT
    m.channel_slug,
    m.kick_user_id,
    MAX(m.username) AS username,
    COUNT(DISTINCT (DATE_TRUNC('day', s.started_at))::DATE) AS active_stream_days,
    COUNT(*) AS messages_during_streams
FROM stream_sessions s
JOIN chat_messages m
  ON m.channel_slug = s.channel_slug
 AND m.created_at >= s.started_at
 AND (s.ended_at IS NULL OR m.created_at <= s.ended_at)
WHERE NOT COALESCE(m.is_command, FALSE)
GROUP BY m.channel_slug, m.kick_user_id
ORDER BY m.channel_slug, active_stream_days DESC, messages_during_streams DESC;
