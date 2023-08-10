#!/usr/bin/env python

import argparse
import glob
import os
import sys
import db
import yt

import yt_dlp

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from models import Playlist, Video
from pathlib import Path

# According to the yt-dlp documentation, this format selection will get the
# best mp4 video available, or failing that, the best video otherwise available.
FORMAT_SELECTION = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b"


def get_args():
    parser = argparse.ArgumentParser(description="Command-line interface for managing channels, videos, and playlists.")
    subparsers = parser.add_subparsers(dest="command_group", help="Sub-command help")

    channels_parser = subparsers.add_parser("channels", help="Manage channels")
    channels_subparser = channels_parser.add_subparsers(dest="channels_command")
    channels_subparser.add_parser("ls", help="List all the channels in the cache")
    channels_subparser.add_parser("generate-index", help="Generate index for a channel").add_argument("channel_name", help="The name of the channel")

    videos_parser = subparsers.add_parser("videos", help="Manage videos")
    videos_subparser = videos_parser.add_subparsers(dest="videos_command")
    videos_subparser.add_parser("get", help="Use the YouTube API to get a list of the videos for a channel").add_argument("channel_name", help="The name of the channel")
    videos_subparser.add_parser("update-root-path", help="Update the root path of all the videos to the currently set path. This is useful if you've changed the root.")
    ls_parser = videos_subparser.add_parser("ls", help="List all the videos in the cache")
    ls_parser.add_argument("channel_name", help="The name of the channel")
    ls_parser.add_argument("--not-downloaded", action="store_true", help="Display only videos that haven't yet been downloaded")
    download_parser = videos_subparser.add_parser("download", help="Download all the listed videos for a channel")
    download_parser.add_argument("channel_name", help="The name of the channel")
    download_parser.add_argument("--skip-ids", type=str, help="A comma-separated list of video IDs to skip")

    playlists_parser = subparsers.add_parser("playlists", help="Manage playlists")
    playlists_subparser = playlists_parser.add_subparsers(dest="playlists_command")
    ls_playlist_parser = playlists_subparser.add_parser("ls", help="List playlists for a channel")
    ls_playlist_parser.add_argument("channel_name", help="The name of the channel")
    ls_playlist_parser.add_argument("--add-unlisted", action="store_true", help="Add unlisted videos to the cache")
    ls_playlist_parser.add_argument("--add-external", action="store_true", help="Add videos that are external to the channel to the cache")
    playlists_subparser.add_parser("get", help="Get playlists for a channel").add_argument("channel_name", help="The name of the channel")
    playlists_subparser.add_parser("download", help="Download playlists for a channel").add_argument("channel_name", help="The name of the channel")
    playlists_subparser.add_parser("delete", help="Delete playlists for a channel").add_argument("channel_name", help="The name of the channel")

    return parser.parse_args()


def get_videos_for_channel(channel_name):
    download_root_path = os.getenv("YT_CH_ARCHIVER_ROOT_PATH")
    if not download_root_path:
        raise Exception(
            "The YT_CH_ARCHIVER_ROOT_PATH environment variable must be set"
        )
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_name(cursor, channel_name)
    download_path = os.path.join(download_root_path, channel_name)
    videos = db.get_videos(cursor, channel_id, False)
    cursor.close()
    conn.close()
    return (videos, download_path)


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
    print(f"{channel_id}")
    videos = db.get_videos(cursor, channel_id, not_downloaded)
    for video in videos:
        video.print()
    cursor.close()
    conn.close()


def process_update_root_path_command():
    download_root_path = os.getenv("YT_CH_ARCHIVER_ROOT_PATH")
    if not download_root_path:
        raise Exception(
            "The YT_CH_ARCHIVER_ROOT_PATH environment variable must be set"
        )
    download_root_path = Path(download_root_path)
    (conn, cursor) = db.create_or_get_conn()
    videos = db.get_downloaded_videos(cursor)
    channels = db.get_channels(cursor)
    for video in videos:
        if video.saved_path:
            current_path = Path(video.saved_path)
            current_root_path = Path(video.saved_path).parent.parent.parent
            if download_root_path != current_root_path:
                new_path = download_root_path.joinpath(
                    channels[video.channel_id]).joinpath("video").joinpath(current_path.name)
                db.save_video_path(cursor, str(new_path), video.id)
    conn.commit()
    cursor.close()
    conn.close()
    pass


def process_get_videos_command(youtube, channel_name):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = yt.get_channel_info(youtube, channel_name)
    db.save_channel(cursor, channel_id, channel_name)
    videos = yt.get_channel_videos(youtube, channel_id)
    for video in videos:
        db.save_video(cursor, video)
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
    failed_videos = {}
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
            try:
                ydl.download([video.get_url()])
                full_video_path = get_full_video_path(
                    os.path.join(download_path, "video"), video.id
                )
                (conn, cursor) = db.create_or_get_conn()
                db.save_video_path(cursor, full_video_path, video.id)
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Failed to download {video.id}:")
                print(e)
                failed_videos[video.id] = e
                continue
    for video_id in failed_videos:
        print(f"Failed to download {video_id}: {failed_videos[video_id]}")


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
                    db.save_video(cursor, Video.from_playlist_item(item))
            if add_external:
                if item.is_external:
                    db.save_video(cursor, Video.from_playlist_item(item))
    conn.commit()
    cursor.close()
    conn.close()


def process_get_playist_command(youtube, channel_name):
    print(f"Getting playlists {channel_name} from YouTube")
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_name(cursor, channel_name)
    playlists = yt.get_playlists_for_channel(youtube, channel_id)

    video_ids = db.get_all_video_ids(cursor)
    # The `playlists` list will be updated with the items.
    yt.get_playlist_items(youtube, cursor, playlists, video_ids)

    for playlist in playlists:
        db.save_playlist(cursor, playlist)
        for playlist_item in playlist.items:
            db.save_playlist_item(cursor, playlist.id, playlist_item)
    conn.commit()
    cursor.close()
    conn.close()


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
    if args.command_group == "channels":
        if args.channels_command == "generate-index":
            process_generate_index_command(args.channel_name)
        elif args.channels_command == "ls":
            process_list_channel_command()
    elif args.command_group == "videos":
        if args.videos_command == "download":
            skip_ids = []
            if args.skip_ids:
                skip_ids = args.skip_ids.split(",")
            process_download_command(args.channel_name, skip_ids)
        elif args.videos_command == "get":
            process_get_videos_command(youtube, args.channel_name)
        elif args.videos_command == "ls":
            process_list_videos_command(args.channel_name, args.not_downloaded)
        elif args.videos_command == "update-root-path":
            process_update_root_path_command()
    elif args.command_group == "playlists":
        if args.playlists_command == "download":
            raise Exception("Not implemented yet")
        elif args.playlists_command == "get":
            process_get_playist_command(youtube, args.channel_name)
        elif args.playlists_command == "ls":
            process_list_playlists_command(args.channel_name, args.add_unlisted, args.add_external)
        elif args.playlists_command == "delete":
            process_delete_playist_command(args.channel_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
