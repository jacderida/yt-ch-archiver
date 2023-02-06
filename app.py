#!/usr/bin/env python

import argparse
import glob
import os
import sqlite3
import sys

import yt_dlp

from bs4 import BeautifulSoup
from googleapiclient.discovery import build

# According to the yt-dlp documentation, this format selection will get the
# best mp4 video available, or failing that, the best video otherwise available.
FORMAT_SELECTION = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b"


class Video:
    def __init__(self, id, title, saved_path):
        self.id = id
        self.title = title
        self.saved_path = saved_path

    def get_url(self):
        return f"http://www.youtube.com/watch?v={self.id}"

    @staticmethod
    def from_search_response_item(youtube, item):
        id = item["id"]["videoId"]
        response = youtube.videos().list(part="snippet", id=id).execute()
        title = response["items"][0]["snippet"]["title"]
        print(f"Retrieved {id}: {title}")
        return Video(id, title, False)

    @staticmethod
    def from_row(row):
        id = row[0]
        title = row[2]
        saved_path = row[3]
        return Video(id, title, saved_path)


def get_args():
    parser = argparse.ArgumentParser(description="YouTube Channel Archiver")
    subparsers = parser.add_subparsers(title="subcommands", dest="subcommand")
    list_parser = subparsers.add_parser("list", help="List all videos for a channel")
    list_parser.add_argument(
        "channel_name",
        type=str,
        help="The name of the channel whose videos you want to list",
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
    return (conn, cursor)


def get_video_list(channel_id, cursor):
    videos = []
    cursor.execute("SELECT * FROM videos WHERE channel_id = ?", (channel_id,))
    rows = cursor.fetchall()
    for row in rows:
        video = Video.from_row(row)
        videos.append(video)
    return videos


def get_videos_for_channel(channel_id):
    download_root_path = os.getenv("YT_CH_ARCHIVER_ROOT_PATH")
    if not download_root_path:
        raise Exception(
            "The YT_CH_ARCHIVER_ROOT_PATH environment variable must be set with your API key"
        )
    (conn, cursor) = create_or_get_db_conn()
    channel_name = get_channel_name_from_db(cursor, channel_id)
    download_path = os.path.join(download_root_path, channel_name)
    videos = get_video_list(channel_id, cursor)
    cursor.close()
    conn.close()
    return (videos, download_path, channel_name)


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


def process_list_command(youtube, channel_name):
    (conn, cursor) = create_or_get_db_conn()
    (channel_id, channel_is_cached) = get_channel_info(youtube, cursor, channel_name)

    videos = []
    print(f"Getting video list for {channel_id}")
    if channel_is_cached:
        print(f"Retrieving {channel_id} videos from cache...")
        videos.extend(get_video_list(channel_id, cursor))
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
        print(f"{video.id}: {video.title}")


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


def main():
    api_key = os.getenv("YT_CH_ARCHIVER_API_KEY")
    if not api_key:
        raise Exception(
            "The YT_CH_ARCHIVER_API_KEY environment variable must be set with your API key"
        )
    args = get_args()
    youtube = build("youtube", "v3", developerKey=api_key)
    if args.subcommand == "list":
        process_list_command(youtube, args.channel_name)
    elif args.subcommand == "list-channels":
        process_list_channel_command()
    elif args.subcommand == "download":
        process_download_command(args.channel_id)
    elif args.subcommand == "generate-index":
        process_generate_index_command(args.channel_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
