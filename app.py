#!/usr/bin/env python

import argparse
import glob
import os
import sys
import db

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
    def __init__(self, id, title, channel_id, saved_path, is_unlisted, is_private):
        self.id = id
        self.title = title
        self.channel_id = channel_id
        self.saved_path = saved_path
        self.is_unlisted = is_unlisted
        self.is_private = is_private

    def get_url(self):
        return f"http://www.youtube.com/watch?v={self.id}"

    @staticmethod
    def from_search_response_item(youtube, item, channel_id):
        id = item["id"]["videoId"]
        response = youtube.videos().list(part="snippet", id=id).execute()
        title = response["items"][0]["snippet"]["title"]
        print(f"Retrieved {id}: {title}")
        return Video(id, title, channel_id, "", False, False)

    @staticmethod
    def from_playlist_item(playlist_item):
        return Video(
            playlist_item.video_id,
            playlist_item.title,
            playlist_item.channel_id,
            "",
            playlist_item.is_unlisted,
            playlist_item.is_private,
        )

    @staticmethod
    def from_row(row):
        id = row[0]
        channel_id = row[1]
        title = row[2]
        saved_path = row[3]
        is_unlisted = row[4]
        is_private = row[5]
        return Video(id, title, channel_id, saved_path, is_unlisted, is_private)

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
            position,
            is_unlisted,
            is_private,
            is_external,
            is_deleted,
        ):
            self.id = id
            self.video_id = video_id
            self.channel_id = channel_id
            self.title = title
            self.position = position
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
                console.print(f"{self.title} [UNLISTED]")
            elif self.is_external:
                console.print(f"{self.title} [EXTERNAL]")
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
        position,
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
            position,
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
    subparsers.add_parser(
        "list-channels", help="List all the channels that have been used"
    )

    list_videos_parser = subparsers.add_parser(
        "list-videos",
        help="List all the locally cached videos for a channel. Green rows indicate the video has been downloaded, while those in red have not.",
    )
    list_videos_parser.add_argument(
        "channel_name",
        type=str,
        help="The name of the channel whose videos you want to list",
    )
    list_videos_parser.add_argument(
        "--not-downloaded",
        action="store_true",
        help="Filter the list to only show videos not downloaded yet",
    )

    list_playlists_parser = subparsers.add_parser(
        "list-playlists",
        help="List all the locally cached playlists for a channel",
    )
    list_playlists_parser.add_argument(
        "channel_name",
        type=str,
        help="The name of the channel whose playlists you want to list",
    )
    list_playlists_parser.add_argument(
        "--add-unlisted",
        action="store_true",
        help="Add unlisted videos from the playlist to the videos cache",
    )
    list_playlists_parser.add_argument(
        "--add-external",
        action="store_true",
        help="Add external videos from the playlist to the videos cache",
    )

    download_parser = subparsers.add_parser(
        "download", help="Download all videos for a channel"
    )
    download_parser.add_argument(
        "channel_name",
        type=str,
        help="The name of the channel whose videos you want to download",
    )
    download_parser.add_argument(
        "--skip-ids",
        type=str,
        help="A comma-separated list of video IDs to skip",
    )

    generate_index_parser = subparsers.add_parser(
        "generate-index",
        help="Generate an index file for the videos downloaded from a channel",
    )
    generate_index_parser.add_argument(
        "channel_name",
        type=str,
        help="The name of the channel for the index you want to generate",
    )

    get_videos_parser = subparsers.add_parser(
        "get-videos",
        help="Obtain a list of all the videos for a channel and cache the list locally",
    )
    get_videos_parser.add_argument(
        "channel_name",
        help="The name of the channel whose playlists you wish to obtain",
    )

    get_playlists_parser = subparsers.add_parser(
        "get-playlists",
        help="Obtain a list of all the playlists for a channel and cache the list locally",
    )
    get_playlists_parser.add_argument(
        "channel_name",
        help="The name of the channel whose playlists you wish to obtain",
    )

    delete_playlists_parser = subparsers.add_parser(
        "delete-playlists",
        help="Deletes all cached playlists for a given channel",
    )
    delete_playlists_parser.add_argument(
        "channel_name",
        help="The name of the channel whose playlists you wish to delete",
    )

    return parser.parse_args()


def get_channel_info(youtube, cursor, channel_name):
    request = youtube.search().list(
        part="snippet", type="channel", q=channel_name, maxResults=1
    )
    response = request.execute()
    if len(response["items"]) == 0:
        raise Exception(f"Could not obtain a channel ID for {channel_name}")
    channel_id = response["items"][0]["snippet"]["channelId"]
    print(f"The channel ID for {channel_name} is {channel_id}")
    db.save_channel(cursor, channel_id, channel_name)
    return channel_id


def get_all_video_ids(cursor):
    video_ids = []
    cursor.execute("SELECT id FROM videos")
    rows = cursor.fetchall()
    for row in rows:
        video_ids.append(row[0])
    return video_ids


def get_videos_for_channel(channel_name):
    download_root_path = os.getenv("YT_CH_ARCHIVER_ROOT_PATH")
    if not download_root_path:
        raise Exception(
            "The YT_CH_ARCHIVER_ROOT_PATH environment variable must be set with your API key"
        )
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_name(cursor, channel_name)
    download_path = os.path.join(download_root_path, channel_name)
    videos = db.get_videos(cursor, channel_id, False)
    cursor.close()
    conn.close()
    return (videos, download_path)


def get_playlists_for_channel(youtube, channel_name):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_name(cursor, channel_name)

    playlists = []
    print(f"Getting playlists {channel_name} from YouTube")
    next_page_token = None
    while True:
        playlist_response = (
            youtube.playlists()
            .list(
                part="id,snippet",
                channelId=channel_id,
                maxResults=50,
                pageToken=next_page_token,
            )
            .execute()
        )
        for playlist in playlist_response["items"]:
            title = playlist["snippet"]["title"]
            print(f"Retrieved playlist {title}...")
            playlist = Playlist(playlist["id"], title, channel_id)
            db.save_playlist(cursor, playlist)
            playlists.append(playlist)
        conn.commit()
        next_page_token = playlist_response.get("nextPageToken")
        if not next_page_token:
            break
    return playlists


def get_playlist_items(youtube, playlists):
    (conn, cursor) = db.create_or_get_conn()

    video_ids = get_all_video_ids(cursor)
    for playlist in playlists:
        print(f"Obtaining items for playlist {playlist.title}")

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
            video_id = item["snippet"]["resourceId"]["videoId"]
            title = item["snippet"]["title"]
            position = item["snippet"]["position"]
            if title == "Private video" or title == "Deleted video":
                channel_id = playlist.channel_id
            else:
                channel_id = item["snippet"]["videoOwnerChannelId"]
                channel_name = item["snippet"]["videoOwnerChannelTitle"]
                db.save_channel(cursor, channel_id, channel_name)

            is_external = 1 if channel_id != playlist.channel_id else 0
            is_unlisted = 1 if not is_external and video_id not in video_ids else 0
            is_private = 1 if title == "Private video" else 0
            is_deleted = 1 if title == "Deleted video" else 0
            playlist_item = playlist.add_item(
                item["id"],
                video_id,
                channel_id,
                title,
                int(position),
                is_unlisted,
                is_private,
                is_external,
                is_deleted,
            )
            print(f"Retrieved playlist item {title}")
            db.save_playlist_item(cursor, playlist.id, playlist_item)
        conn.commit()
    cursor.close()
    conn.close()


def add_video_from_playlist_item(playlist_item):
    (conn, cursor) = db.create_or_get_conn()
    db.save_video(cursor, Video.from_playlist_item(playlist_item))
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


def process_list_videos_command(channel_name, not_downloaded):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_name(cursor, channel_name)
    videos = db.get_videos(cursor, channel_id, not_downloaded)
    for video in videos:
        video.print()
    cursor.close()
    conn.close()


def process_get_videos_command(youtube, channel_name):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = get_channel_info(youtube, cursor, channel_name)

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
            video = Video.from_search_response_item(youtube, item, channel_id)
            db.save_video(cursor, video)
        next_page_token = search_response.get("nextPageToken")
        if not next_page_token:
            break
    conn.commit()
    cursor.close()
    conn.close()


def process_list_channel_command():
    (conn, cursor) = db.create_or_get_conn()
    cursor.execute("SELECT * FROM channels")
    rows = cursor.fetchall()
    for row in rows:
        id = row[0]
        name = row[1]
        print(f"{id}: {name}")
    cursor.close()
    conn.close()


def process_download_command(channel_name, skip_ids):
    (videos, download_path) = get_videos_for_channel(channel_name)
    print(f"Attempting to download videos for {channel_name}...")
    for video in videos:
        if video.saved_path and os.path.exists(video.saved_path):
            print(f"{video.id} has already been downloaded. Skipping.")
            continue
        if video.is_private:
            print(f"{video.id} is a private video. Skipping.")
            continue
        if video.id in skip_ids:
            print(f"{video.id} was on skip list. Skipping.")
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
            (conn, cursor) = db.create_or_get_conn()
            cursor.execute(
                """
                UPDATE videos SET saved_path = ? WHERE id = ?
                """,
                (full_video_path, video.id),
            )
            conn.commit()
            cursor.close()
            conn.close()


def process_generate_index_command(channel_name):
    (videos, download_path) = get_videos_for_channel(channel_name)
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


def process_list_playlists_command(channel_name, add_unlisted, add_external):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_name(cursor, channel_name)
    playlists = db.get_playlists(cursor, channel_id)
    for playlist in playlists:
        db.get_playlist_items(cursor, playlist)
        playlist.print_title()
        for item in playlist.items:
            item.print()
            if add_unlisted:
                if item.is_unlisted and not item.is_private and not item.is_deleted:
                    add_video_from_playlist_item(item)
            if add_external:
                if item.is_external:
                    add_video_from_playlist_item(item)
    conn.commit()
    cursor.close()
    conn.close()


def process_get_playist_command(youtube, channel_name):
    playlists = get_playlists_for_channel(youtube, channel_name)
    get_playlist_items(youtube, playlists)


def process_delete_playist_command(channel_name):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_name(cursor, channel_name)
    db.delete_playlists(cursor, channel_id)
    conn.commit()
    cursor.close()
    conn.close()
    print(f"Deleted playlists for {channel_name}")


def main():
    api_key = os.getenv("YT_CH_ARCHIVER_API_KEY")
    if not api_key:
        raise Exception(
            "The YT_CH_ARCHIVER_API_KEY environment variable must be set with your API key"
        )
    args = get_args()
    youtube = build("youtube", "v3", developerKey=api_key)
    if args.subcommand == "delete-playlists":
        process_delete_playist_command(args.channel_name)
    elif args.subcommand == "download":
        skip_ids = []
        if args.skip_ids:
            skip_ids = args.skip_ids.split(",")
        process_download_command(args.channel_name, skip_ids)
    elif args.subcommand == "generate-index":
        process_generate_index_command(args.channel_name)
    elif args.subcommand == "get-playlists":
        process_get_playist_command(youtube, args.channel_name)
    elif args.subcommand == "get-videos":
        process_get_videos_command(youtube, args.channel_name)
    elif args.subcommand == "list-channels":
        process_list_channel_command()
    elif args.subcommand == "list-playlists":
        process_list_playlists_command(
            args.channel_name, args.add_unlisted, args.add_external
        )
    elif args.subcommand == "list-videos":
        process_list_videos_command(args.channel_name, args.not_downloaded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
