#!/usr/bin/env python

import argparse
import glob
import os
import sqlite3
import sys

import yt_dlp

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.text import Text
from rich.theme import Theme

# According to the yt-dlp documentation, this format selection will get the
# best mp4 video available, or failing that, the best video otherwise available.
FORMAT_SELECTION = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b"


class Video:
    def __init__(self, id, title, saved_path, is_unlisted, is_private):
        self.id = id
        self.title = title
        self.saved_path = saved_path
        self.is_unlisted = is_unlisted
        self.is_private = is_private

    def get_url(self):
        return f"http://www.youtube.com/watch?v={self.id}"

    @staticmethod
    def from_search_response_item(youtube, item):
        id = item["id"]["videoId"]
        response = youtube.videos().list(part="snippet", id=id).execute()
        title = response["items"][0]["snippet"]["title"]
        print(f"Retrieved {id}: {title}")
        return Video(id, title, "", False, False)

    @staticmethod
    def from_row(row):
        id = row[0]
        title = row[2]
        saved_path = row[3]
        is_unlisted = row[4]
        is_private = row[5]
        return Video(id, title, saved_path, is_unlisted, is_private)

    def print(self):
        theme = Theme({"hl.word_unlisted": "blue", "hl.word_external": "yellow"})
        console = Console(highlighter=WordHighlighter(), theme=theme)
        msg = f"{self.id}: {self.title}"
        if self.is_unlisted or self.is_private:
            msg += " ["
            if self.is_unlisted:
                msg += "UNLISTED, "
            if self.is_private:
                msg += "PRIVATE"
            msg = msg.removesuffix(", ")
            msg += "]"
        if self.saved_path:
            console.print(msg, style="green")
        else:
            console.print(msg, style="red")


class WordHighlighter(RegexHighlighter):
    base_style = "hl."
    highlights = [r"(?P<word_unlisted>UNLISTED)", "(?P<word_external>EXTERNAL)"]


class Playlist:
    def __init__(self, id, title, channel_id):
        self.id = id
        self.title = title
        self.channel_id = channel_id
        self.items = []

    class PlaylistItem:
        def __init__(
            self,
            id,
            video_id,
            channel_id,
            title,
            is_unlisted,
            is_private,
            is_external,
            is_deleted,
        ):
            self.id = id
            self.video_id = video_id
            self.channel_id = channel_id
            self.title = title
            self.is_unlisted = True if is_unlisted == 1 else False
            self.is_private = True if is_private == 1 else False
            self.is_external = True if is_external == 1 else False
            self.is_deleted = True if is_deleted == 1 else False

        def print(self):
            theme = Theme({"hl.word_unlisted": "blue", "hl.word_external": "yellow"})
            console = Console(highlighter=WordHighlighter(), theme=theme)
            if self.is_private:
                console.print(f"{self.title}", style="red")
            elif self.is_deleted:
                console.print(f"{self.title}", style="red")
            elif self.is_unlisted:
                console.print(f"{self.title} UNLISTED")
            elif self.is_external:
                console.print(f"{self.title} EXTERNAL")
            else:
                console.print(f"{self.title}")

    def print_title(self):
        header = f"{self.title} ({len(self.items)} items)"
        console = Console()
        console.print(Text("=" * len(header), style="green"))
        console.print(f"{header}", style="green")
        console.print(Text("=" * len(header), style="green"))

    def add_item(
        self,
        id,
        video_id,
        channel_id,
        title,
        is_unlisted,
        is_private,
        is_external,
        is_deleted,
    ):
        item = self.PlaylistItem(
            id,
            video_id,
            channel_id,
            title,
            is_unlisted,
            is_private,
            is_external,
            is_deleted,
        )
        self.items.append(item)
        return item


def get_args():
    parser = argparse.ArgumentParser(description="YouTube Channel Archiver")
    subparsers = parser.add_subparsers(title="subcommands", dest="subcommand")
    list_parser = subparsers.add_parser(
        "list",
        help="List all videos for a channel and cache them locally. Videos in green have been downloaded, while those in red have not.",
    )
    list_parser.add_argument(
        "channel_name",
        type=str,
        help="The name of the channel whose videos you want to list",
    )
    list_parser.add_argument(
        "--not-downloaded",
        action="store_true",
        help="Filter the list to only show videos not downloaded yet",
    )
    subparsers.add_parser(
        "list-channels", help="List all the channels that have been used"
    )
    download_parser = subparsers.add_parser(
        "download", help="Download all videos for a channel"
    )
    download_parser.add_argument(
        "channel_id",
        type=str,
        help="The ID of the channel whose videos you want to download",
    )
    index_parser = subparsers.add_parser(
        "generate-index",
        help="Generate an index file for the videos downloaded from a channel",
    )
    index_parser.add_argument(
        "channel_id",
        type=str,
        help="The ID of the channel for the index you want to generate",
    )
    playlist_parser = subparsers.add_parser(
        "get-playlists",
        help="Obtain all the playlists for a channel and cache them locally",
    )
    playlist_parser.add_argument(
        "channel_id", help="The ID of the channel whose playlists you wish to obtain"
    )
    playlist_parser.add_argument(
        "--add-unlisted",
        action="store_true",
        help="Add unlisted videos from the playlist to the videos cache",
    )
    return parser.parse_args()


def get_channel_name_from_db(cursor, channel_id):
    print(f"Using channel_id: {channel_id}")
    cursor.execute("SELECT name FROM channels WHERE id = ?", (channel_id,))
    channel_name = cursor.fetchone()
    if not channel_name:
        raise Exception(
            f"The cache has no channel with ID {channel_id}. Please run the `list` command to first get a list of videos for the channel."
        )
    return channel_name[0]


def get_channel_info(youtube, cursor, channel_name):
    print(f"Obtaining channel info for {channel_name}")
    cursor.execute("SELECT id FROM channels WHERE name = ?", (channel_name,))
    result = cursor.fetchone()
    if result:
        channel_id = result[0]
        print(f"{channel_name} is in the cache")
        print(f"The channel ID for {channel_name} is {channel_id}")
        return (channel_id, True)
    request = youtube.search().list(
        part="snippet", type="channel", q=channel_name, maxResults=1
    )
    response = request.execute()
    if len(response["items"]) == 0:
        raise Exception(f"Could not obtain a channel ID for {channel_name}")
    channel_id = response["items"][0]["snippet"]["channelId"]
    cursor.execute(
        """
    INSERT OR IGNORE INTO channels (id, name)
    VALUES (?, ?)
    """,
        (channel_id, channel_name),
    )
    print(f"The channel ID for {channel_name} is {channel_id}")
    return (channel_id, False)


def create_or_get_db_conn():
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


def get_video_list(channel_id, cursor, not_downloaded):
    videos = []
    query = "SELECT * FROM videos WHERE channel_id = ?"
    if not_downloaded:
        query += " AND saved_path IS NULL;"
    cursor.execute(query, (channel_id,))
    rows = cursor.fetchall()
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


def get_videos_for_channel(channel_id):
    download_root_path = os.getenv("YT_CH_ARCHIVER_ROOT_PATH")
    if not download_root_path:
        raise Exception(
            "The YT_CH_ARCHIVER_ROOT_PATH environment variable must be set with your API key"
        )
    (conn, cursor) = create_or_get_db_conn()
    channel_name = get_channel_name_from_db(cursor, channel_id)
    download_path = os.path.join(download_root_path, channel_name)
    videos = get_video_list(channel_id, cursor, False)
    cursor.close()
    conn.close()
    return (videos, download_path, channel_name)


def get_playlists_for_channel(youtube, channel_id):
    (conn, cursor) = create_or_get_db_conn()
    channel_name = get_channel_name_from_db(cursor, channel_id)

    print(f"Obtaining playlists for {channel_name}")
    playlists = []
    cursor.execute(
        "SELECT id, title, channel_id FROM playlists WHERE channel_id = ?",
        (channel_id,),
    )
    rows = cursor.fetchall()
    if len(rows) > 0:
        print("Using playlists from cache")
        for row in rows:
            playlist = Playlist(row[0], row[1], row[2])
            playlists.append(playlist)
        return playlists

    print("Getting playlists from YouTube")
    next_page_token = None
    while True:
        playlist_response = (
            youtube.playlists()
            .list(part="id,snippet", channelId=channel_id, maxResults=50)
            .execute()
        )
        for playlist in playlist_response["items"]:
            playlist = Playlist(
                playlist["id"], playlist["snippet"]["title"], channel_id
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO playlists (id, channel_id, title)
                VALUES (?, ?, ?)
                """,
                (playlist.id, playlist.channel_id, playlist.title),
            )
            playlists.append(playlist)
        conn.commit()
        next_page_token = playlist_response.get("nextPageToken")
        if not next_page_token:
            break
    return playlists


def get_playlist_items(youtube, playlists):
    (conn, cursor) = create_or_get_db_conn()

    video_ids = get_all_video_ids(cursor)
    for playlist in playlists:
        print(f"Obtaining items for playlist {playlist.id}")
        cursor.execute(
            """
            SELECT id, video_id, channel_id, title, is_unlisted, is_private, is_external, is_deleted
            FROM playlist_items WHERE playlist_id = ?
            """,
            (playlist.id,),
        )
        rows = cursor.fetchall()
        if len(rows) > 0:
            print("Using playlist items from cache")
            for row in rows:
                playlist.add_item(
                    row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]
                )
            continue

        next_page_token = None
        items = []
        while True:
            playlist_items_response = (
                youtube.playlistItems()
                .list(
                    part="id,snippet",
                    playlistId=playlist.id,
                    maxResults=50,
                    pageToken=next_page_token,
                )
                .execute()
            )

            items.extend(playlist_items_response.get("items", []))
            next_page_token = playlist_items_response.get("nextPageToken")
            if not next_page_token:
                break
            print("Getting next page of playlist items...")
        for item in items:
            is_unlisted = (
                1 if item["snippet"]["resourceId"]["videoId"] not in video_ids else 0
            )
            is_private = 1 if item["snippet"]["title"] == "Private video" else 0
            is_deleted = 1 if item["snippet"]["title"] == "Deleted video" else 0
            is_external = (
                1 if item["snippet"]["channelId"] != playlist.channel_id else 0
            )
            playlist_item = playlist.add_item(
                item["id"],
                item["snippet"]["resourceId"]["videoId"],
                item["snippet"]["channelId"],
                item["snippet"]["title"],
                is_unlisted,
                is_private,
                is_external,
                is_deleted,
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO playlist_items (
                    id, playlist_id, video_id, channel_id,
                    title, is_unlisted, is_private, is_external, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    playlist_item.id,
                    playlist.id,
                    playlist_item.video_id,
                    playlist_item.channel_id,
                    playlist_item.title,
                    is_unlisted,
                    is_private,
                    is_external,
                    is_deleted,
                ),
            )
        conn.commit()
    cursor.close()
    conn.close()


def add_unlisted_video(playlist_item):
    (conn, cursor) = create_or_get_db_conn()
    cursor.execute(
        """
        INSERT OR IGNORE INTO videos (id, channel_id, title, is_unlisted, is_private)
        VALUES (?, ?, ?, ?)
        """,
        (
            playlist_item.video_id,
            playlist_item.channel_id,
            playlist_item.title,
            1,
            playlist_item.is_private,
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_full_video_path(download_path, video_id):
    """
    Before calling yt-dlp, it's not possible to know the file extension of the
    file it will save. Here we will use a filter and take the first file in the
    list (there should only be one item in the list) in the `video` subdirectory.

    We have to exclude thumbnail files from the output. The documentation for
    yt-dlp implies that thumbnails can be output to a separate path like the
    info and description files, but it doesn't work, so the thumbnails are also
    getting written out to the `video` subdirectory.
    """
    pattern = os.path.join(download_path, f"{video_id}.[!webp|jpg]*")
    files = glob.glob(pattern)
    return files[0]


def get_video_thumbnail_path(download_path, video_id):
    """
    Get the downloaded or generated thumbnail for a video, which is either a jpg or a webp.
    """
    pattern = os.path.join(download_path, f"{video_id}.webp")
    pattern2 = os.path.join(download_path, f"{video_id}.jpg")
    files = glob.glob(pattern) + glob.glob(pattern2)
    if len(files) == 0:
        raise Exception(f"{video_id} has no thumbnail")
    return files[0]


def get_video_description(download_path, video_id):
    path = os.path.join(download_path, "description", f"{video_id}.description")
    with open(path, "r") as f:
        description = f.read()
        return description


def process_list_command(youtube, channel_name, not_downloaded):
    (conn, cursor) = create_or_get_db_conn()
    (channel_id, channel_is_cached) = get_channel_info(youtube, cursor, channel_name)

    videos = []
    print(f"Getting video list for {channel_id}")
    if channel_is_cached:
        print(f"Retrieving {channel_id} videos from cache...")
        videos.extend(get_video_list(channel_id, cursor, not_downloaded))
    else:
        print(f"{channel_id} is not cached. Will retrieve video list from YouTube...")
        next_page_token = None
        while True:
            search_response = (
                youtube.search()
                .list(
                    part="id",
                    channelId=channel_id,
                    type="video",
                    maxResults=50,
                    pageToken=next_page_token,
                )
                .execute()
            )
            for item in search_response["items"]:
                video = Video.from_search_response_item(youtube, item)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO videos (id, channel_id, title)
                    VALUES (?, ?, ?)
                    """,
                    (video.id, channel_id, video.title),
                )
                videos.append(video)
            next_page_token = search_response.get("nextPageToken")
            if not next_page_token:
                break
        conn.commit()
    cursor.close()
    conn.close()
    for video in videos:
        video.print()


def process_list_channel_command():
    (conn, cursor) = create_or_get_db_conn()
    cursor.execute("SELECT * FROM channels")
    rows = cursor.fetchall()
    for row in rows:
        id = row[0]
        name = row[1]
        print(f"{id}: {name}")
    cursor.close()
    conn.close()


def process_download_command(channel_id):
    (videos, download_path, channel_name) = get_videos_for_channel(channel_id)
    print(f"Attempting to download videos for {channel_name}...")
    for video in videos:
        if video.saved_path and os.path.exists(video.saved_path):
            print(f"{video.id} has already been downloaded. Skipping.")
            continue
        if video.is_private:
            print(f"{video.id} is a private video. Skipping.")
            continue
        ydl_opts = {
            "continue": True,
            "cookiesfrombrowser": ("firefox",),
            "format": FORMAT_SELECTION,
            "outtmpl": {
                "default": "%(id)s.%(ext)s",
                "description": "%(id)s.%(ext)s",
                "infojson": "%(id)s.%(ext)s",
            },
            "paths": {
                "home": os.path.join(download_path, "video"),
                "description": os.path.join(download_path, "description"),
                "infojson": os.path.join(download_path, "info"),
            },
            "nooverwrites": True,
            "nopart": True,
            "writedescription": True,
            "writeinfojson": True,
            "writethumbnail": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video.get_url()])
            full_video_path = get_full_video_path(
                os.path.join(download_path, "video"), video.id
            )
            print(
                f"Updating {video.id} cache entry to indicate video saved at {full_video_path}"
            )
            (conn, cursor) = create_or_get_db_conn()
            cursor.execute(
                """
                UPDATE videos SET saved_path = ? WHERE id = ?
                """,
                (full_video_path, video.id),
            )
            conn.commit()
            cursor.close()
            conn.close()


def process_generate_index_command(channel_id):
    (videos, download_path, channel_name) = get_videos_for_channel(channel_id)
    print(f"Generating index for {channel_name}...")
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    body = soup.body
    if not body:
        raise Exception("Body tag not found")
    header = soup.new_tag("header")
    header["style"] = "font-size: 48px"
    header.string = channel_name
    html_tag = soup.find("html")
    if not html_tag:
        raise Exception("Root html tag not found")
    html_tag.insert(0, header)

    for video in videos:
        print(f"Processing {video.id}...")
        div = soup.new_tag("div")
        div["style"] = "border: 1px solid black; padding: 10px"

        title_p = soup.new_tag("p")
        title_p.string = video.title
        title_p["style"] = "font-size: 24px"
        div.append(title_p)

        thumbnail_img = soup.new_tag("img")
        thumbnail_img["src"] = get_video_thumbnail_path(
            os.path.join(download_path, "video"), video.id
        )
        thumbnail_img["alt"] = video.id
        div.append(thumbnail_img)

        youtube_id_p = soup.new_tag("p")
        youtube_id_p.string = f"YouTube Video ID: {video.id}"
        div.append(youtube_id_p)

        description_pre = soup.new_tag("pre")
        description_pre["style"] = "word-wrap: break-word; width: 50%"
        description = get_video_description(download_path, video.id)
        description_pre.string = description
        div.append(description_pre)

        body.append(div)
    index_path = os.path.join(download_path, "index.html")
    print(f"Generating index at {index_path}")
    with open(index_path, "w") as f:
        f.write(soup.prettify())


def process_get_playist_command(youtube, channel_id, add_unlisted):
    playlists = get_playlists_for_channel(youtube, channel_id)
    get_playlist_items(youtube, playlists)
    for playlist in playlists:
        playlist.print_title()
        for item in playlist.items:
            item.print()
            if add_unlisted:
                if item.is_unlisted and not item.is_private and not item.is_deleted:
                    add_unlisted_video(item)


def main():
    api_key = os.getenv("YT_CH_ARCHIVER_API_KEY")
    if not api_key:
        raise Exception(
            "The YT_CH_ARCHIVER_API_KEY environment variable must be set with your API key"
        )
    args = get_args()
    youtube = build("youtube", "v3", developerKey=api_key)
    if args.subcommand == "list":
        process_list_command(youtube, args.channel_name, args.not_downloaded)
    elif args.subcommand == "list-channels":
        process_list_channel_command()
    elif args.subcommand == "download":
        process_download_command(args.channel_id)
    elif args.subcommand == "generate-index":
        process_generate_index_command(args.channel_id)
    elif args.subcommand == "get-playlists":
        process_get_playist_command(youtube, args.channel_id, args.add_unlisted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
