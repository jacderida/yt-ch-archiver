import os
import sqlite3

from app import Video


def create_or_get_conn():
    if "HOME" in os.environ:
        app_data_path = os.path.join(os.environ["HOME"], ".local", "yt-ch-archiver")
    elif "APPDATA" in os.environ:
        app_data_path = os.path.join(os.environ["APPDATA"], "yt-ch-archiver")
    else:
        raise Exception("Could not find home directory")
    if not os.path.exists(app_data_path):
        os.makedirs(app_data_path)
    database_path = os.path.join(app_data_path, "videos.db")
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL
    )
    """
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        saved_path TEXT NULL,
        FOREIGN KEY (channel_id) REFERENCES channels (id)
    )
    """
    )
    cursor.execute("PRAGMA table_info(videos)")
    columns = [row[1] for row in cursor.fetchall()]
    if "is_unlisted" not in columns:
        cursor.execute(
            """
        ALTER TABLE videos
        ADD COLUMN is_unlisted INTEGER NOT NULL DEFAULT 0
        """
        )
    if "is_private" not in columns:
        cursor.execute(
            """
        ALTER TABLE videos
        ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0
        """
        )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS playlists (
        id TEXT PRIMARY KEY,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        FOREIGN KEY (channel_id) REFERENCES channels (id)
    )
    """
    )
    # It's possible for a playlist item to be a video that's not related to the
    # channel that created the playlist.
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS playlist_items (
        id TEXT PRIMARY KEY,
        playlist_id TEXT NOT NULL,
        video_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        is_unlisted INTEGER NOT NULL DEFAULT 0,
        is_private INTEGER NOT NULL DEFAULT 0,
        is_external INTEGER NOT NULL DEFAULT 0,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (playlist_id) REFERENCES playlists (id)
        FOREIGN KEY (video_id) REFERENCES videos (id)
    )
    """
    )
    return (conn, cursor)


def save_channel(cursor, channel_id, channel_name):
    cursor.execute(
        """
    INSERT OR IGNORE INTO channels (id, name)
    VALUES (?, ?)
    """,
        (channel_id, channel_name),
    )


def get_channel_id_from_name(cursor, channel_name):
    cursor.execute("SELECT id FROM channels WHERE name = ?", (channel_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
    raise Exception(f"{channel_name} is not in the local cache")


def get_videos(channel_id, cursor, not_downloaded):
    videos = []
    query = "SELECT * FROM videos WHERE channel_id = ?"
    if not_downloaded:
        query += " AND saved_path IS NULL;"
    cursor.execute(query, (channel_id,))
    rows = cursor.fetchall()
    if len(rows) == 0:
        raise Exception(f"Videos have not been retrieved for channel ID {channel_id}")
    for row in rows:
        video = Video.from_row(row)
        videos.append(video)
    return videos
