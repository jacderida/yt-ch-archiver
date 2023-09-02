import os
import sqlite3

from io import BytesIO
from models import Channel, Playlist, Video


def add_new_column(cursor, table, name, data_type, null_status, default_value):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if name not in columns:
        sql = f"""
        ALTER TABLE {table}
        ADD COLUMN {name} {data_type} {null_status}
        """
        if default_value:
            sql += f" DEFAULT {default_value}"
        cursor.execute(sql)


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
        username TEXT NOT NULL
    )
    """
    )
    add_new_column(cursor, "channels", "title", "TEXT", "NULL", None)
    add_new_column(cursor, "channels", "description", "TEXT", "NULL", None)
    add_new_column(cursor, "channels", "published_at", "TEXT", "NULL", None)
    add_new_column(cursor, "channels", "large_thumbnail", "BLOB", "NULL", None)
    add_new_column(cursor, "channels", "medium_thumbnail", "BLOB", "NULL", None)
    add_new_column(cursor, "channels", "small_thumbnail", "BLOB", "NULL", None)

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
    if "download_error" not in columns:
        cursor.execute(
            """
        ALTER TABLE videos
        ADD COLUMN download_error TEXT NULL
        """
        )
    if "duration" not in columns:
        cursor.execute(
            """
        ALTER TABLE videos
        ADD COLUMN duration TEXT NULL
        """
        )
    if "resolution" not in columns:
        cursor.execute(
            """
        ALTER TABLE videos
        ADD COLUMN resolution TEXT NULL
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


def save_channel(cursor, id, username):
    cursor.execute(
        """
    INSERT OR IGNORE INTO channels (id, username)
    VALUES (?, ?)
    """,
        (id, username),
    )


def save_channel_details(cursor, channel):
    if not channel.small_thumbnail or not channel.medium_thumbnail or not channel.large_thumbnail:
        raise Exception("Thumbnails must be provided for saving channel details")

    cursor.execute(
        """
    INSERT OR IGNORE INTO channels (
        id, username, published_at,
        title, description, large_thumbnail, medium_thumbnail, small_thumbnail)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            channel.id,
            channel.username,
            channel.published_at,
            channel.title,
            channel.description,
            save_thumbnail_as_png_byte_array(channel.large_thumbnail),
            save_thumbnail_as_png_byte_array(channel.medium_thumbnail),
            save_thumbnail_as_png_byte_array(channel.small_thumbnail),
        ),
    )


def save_updated_channel_details(cursor, channel):
    print(f"Saving updated channel information for {channel.title}")
    cursor.execute(
        """
    UPDATE channels SET
        username = ?, published_at = ?,
        title = ?, description = ?, large_thumbnail = ?, medium_thumbnail = ?, small_thumbnail = ?
    WHERE id = ?
    """,
        (
            channel.username,
            channel.published_at,
            channel.title,
            channel.description,
            save_thumbnail_as_png_byte_array(channel.large_thumbnail),
            save_thumbnail_as_png_byte_array(channel.medium_thumbnail),
            save_thumbnail_as_png_byte_array(channel.small_thumbnail),
            channel.id,
        ),
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


def save_downloaded_video_details(cursor, video):
    print(
        f"Updating {video.id} cache entry with downloaded video details"
    )
    cursor.execute(
        """
        UPDATE videos SET saved_path = ?, duration = ?, resolution = ? WHERE id = ?
        """,
        (video.saved_path, video.duration, video.resolution, video.id),
    )


def save_download_error(cursor, video_id, download_error):
    print(
        f"Updating {video_id} cache entry with download error"
    )
    cursor.execute(
        """
        UPDATE videos SET download_error = ? WHERE id = ?
        """,
        (download_error, video_id),
    )


def get_channel_id_from_username(cursor, channel_username):
    cursor.execute("SELECT id FROM channels WHERE username = ?", (channel_username,))
    result = cursor.fetchone()
    if result:
        return result[0]
    raise Exception(f"{channel_username} is not in the local cache")


def get_channel_name_from_id(cursor, channel_id):
    cursor.execute("SELECT name FROM channels WHERE id = ?", (channel_id,))
    result = cursor.fetchone()
    if result:
        return result[0]
    raise Exception(
        f"The cache has no channel with ID {channel_id}. Please run the `list` command to first get a list of videos for the channel."
    )


def get_channel_by_id(cursor, channel_id):
    cursor.execute(
        """
        SELECT id, username, published_at, title, description,
        small_thumbnail, medium_thumbnail, large_thumbnail FROM channels WHERE id = ?
        """,
        (channel_id,))
    result = cursor.fetchone()
    if result:
        return Channel.from_row_with_image_data(result)
    return None


def get_channel_by_username(cursor, username):
    cursor.execute(
        """
        SELECT id, username, published_at, title, description,
        small_thumbnail, medium_thumbnail, large_thumbnail FROM channels WHERE username = ?
        """,
        (username,))
    result = cursor.fetchone()
    if result:
        return Channel.from_row_with_image_data(result)
    return None


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


def get_all_video_ids(cursor):
    video_ids = []
    cursor.execute("SELECT id FROM videos")
    rows = cursor.fetchall()
    for row in rows:
        video_ids.append(row[0])
    return video_ids


def get_downloaded_videos(cursor):
    videos = []
    cursor.execute("SELECT * FROM videos WHERE saved_path IS NOT NULL AND saved_path != ''")
    rows = cursor.fetchall()
    for row in rows:
        video = Video.from_row(row)
        videos.append(video)
    return videos


def get_channels(cursor):
    channels = {}
    query = "SELECT id, username FROM channels"
    cursor.execute(query)
    rows = cursor.fetchall()
    for row in rows:
        channels[row[0]] = row[1]
    return channels


def get_all_channel_info(cursor):
    channels = []
    cursor.execute("SELECT id, username, published_at, title, description FROM channels")
    rows = cursor.fetchall()
    for row in rows:
        channel = Channel.from_row(row)
        channels.append(channel)
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


def get_video_by_id(cursor, video_id):
    cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
    result = cursor.fetchone()
    if result:
        return Video.from_row(result)
    return None


def delete_playlists(cursor, channel_id):
    cursor.execute(
        "DELETE FROM playlist_items WHERE channel_id = ?",
        (channel_id,),
    )
    cursor.execute(
        "DELETE FROM playlists WHERE channel_id = ?",
        (channel_id,),
    )


def delete_all_channel_images(cursor):
    cursor.execute(
        """
        UPDATE channels
        SET large_thumbnail = NULL, medium_thumbnail = NULL, small_thumbnail = NULL
        """
    )


def save_thumbnail_as_png_byte_array(thumbnail_image):
    byte_io = BytesIO()
    thumbnail_image.save(byte_io, "PNG")
    return byte_io.getvalue()
