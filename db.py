import os
import sqlite3

from app import Playlist, Video


def create_or_get_conn():
    if "YT_CH_ARCHIVER_DB_PATH":
        database_path = os.environ["YT_CH_ARCHIVER_DB_PATH"]
    else:
        if "HOME" in os.environ:
            app_data_path = os.path.join(os.environ["HOME"], ".local", "share", "yt-ch-archiver")
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

    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS playlist_items (
        id TEXT PRIMARY KEY,
        playlist_id TEXT NOT NULL,
        video_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        position INTEGER NOT NULL,
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


def save_video(cursor, video):
    cursor.execute(
        """
        INSERT OR IGNORE INTO videos (id, channel_id, title, saved_path, is_unlisted, is_private)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            video.id,
            video.channel_id,
            video.title,
            video.saved_path,
            video.is_unlisted,
            video.is_private,
        ),
    )


def save_playlist(cursor, playlist):
    cursor.execute(
        """
        INSERT OR IGNORE INTO playlists (id, channel_id, title)
        VALUES (?, ?, ?)
        """,
        (playlist.id, playlist.channel_id, playlist.title),
    )


def save_playlist_item(cursor, playlist_id, playlist_item):
    is_unlisted = 1 if playlist_item.is_unlisted else 0
    is_private = 1 if playlist_item.is_private else 0
    is_external = 1 if playlist_item.is_external else 0
    is_deleted = 1 if playlist_item.is_deleted else 0
    cursor.execute(
        """
        INSERT OR IGNORE INTO playlist_items (
            id, playlist_id, video_id, channel_id,
            title, position, is_unlisted, is_private, is_external, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            playlist_item.id,
            playlist_id,
            playlist_item.video_id,
            playlist_item.channel_id,
            playlist_item.title,
            playlist_item.position,
            is_unlisted,
            is_private,
            is_external,
            is_deleted,
        ),
    )


def save_video_path(cursor, full_video_path, video_id):
    print(
        f"Updating {video_id} cache entry to indicate video saved at {full_video_path}"
    )
    cursor.execute(
        """
        UPDATE videos SET saved_path = ? WHERE id = ?
        """,
        (full_video_path, video_id),
    )


def get_channel_id_from_name(cursor, channel_name):
    cursor.execute("SELECT id FROM channels WHERE name = ?", (channel_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
    raise Exception(f"{channel_name} is not in the local cache")


def get_channel_name_from_id(cursor, channel_id):
    cursor.execute("SELECT name FROM channels WHERE id = ?", (channel_id,))
    result = cursor.fetchone()
    if result:
        return result[0]
    raise Exception(
        f"The cache has no channel with ID {channel_id}. Please run the `list` command to first get a list of videos for the channel."
    )


def get_videos(cursor, channel_id, not_downloaded):
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


def get_downloaded_videos(cursor):
    videos = []
    query = "SELECT * FROM videos WHERE saved_path IS NOT NULL"
    cursor.execute(query)
    rows = cursor.fetchall()
    for row in rows:
        video = Video.from_row(row)
        videos.append(video)
    return videos


def get_channels(cursor):
    channels = {}
    query = "SELECT * FROM channels"
    cursor.execute(query)
    rows = cursor.fetchall()
    for row in rows:
        channels[row[0]] = row[1]
    return channels


def get_playlists(cursor, channel_id):
    playlists = []
    cursor.execute(
        "SELECT id, title, channel_id FROM playlists WHERE channel_id = ?",
        (channel_id,),
    )
    rows = cursor.fetchall()
    if len(rows) == 0:
        raise Exception(
            f"Playlists have not been retrieved for channel ID {channel_id}"
        )
    for row in rows:
        playlist = Playlist(row[0], row[1], row[2])
        playlists.append(playlist)
    return playlists


def get_playlist_items(cursor, playlist):
    cursor.execute(
        """
        SELECT id, video_id, channel_id, title, position, is_unlisted, is_private,
          is_external, is_deleted
        FROM playlist_items WHERE playlist_id = ?
        ORDER BY position
        """,
        (playlist.id,),
    )
    rows = cursor.fetchall()
    for row in rows:
        playlist.add_item(
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8]
        )


def get_all_downloaded_video_ids(cursor):
    cursor.execute(
        """
        SELECT id FROM videos WHERE saved_path NOT NULL
        """
    )
    rows = cursor.fetchall()
    return [row[0] for row in rows]


def delete_playlists(cursor, channel_id):
    cursor.execute(
        "DELETE FROM playlist_items WHERE channel_id = ?",
        (channel_id,),
    )
    cursor.execute(
        "DELETE FROM playlists WHERE channel_id = ?",
        (channel_id,),
    )
