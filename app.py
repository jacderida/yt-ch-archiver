#!/usr/bin/env python

import argparse
import cmds
import os
import sys


from googleapiclient.discovery import build


def get_args():
    parser = argparse.ArgumentParser(description="Command-line interface for managing channels, videos, and playlists.")
    subparsers = parser.add_subparsers(dest="command_group", help="Sub-command help")

    admin_parser = subparsers.add_parser("admin", help="Manage channels")
    admin_subparser = admin_parser.add_subparsers(dest="admin_command")
    admin_subparser.add_parser(
        "build-thumbnails",
        help="Build thumbnails for videos that have already been retrieved").add_argument(
            "channel_name", help="The name of the channel")
    admin_subparser.add_parser(
        "update-root-path",
        help="Update the root path of all the videos to the currently set path")
    admin_subparser.add_parser(
        "update-video-info",
        help="Update video cache records with duration and resolution").add_argument(
            "channel_name", help="The name of the channel")

    channels_parser = subparsers.add_parser("channels", help="Manage channels")
    channels_subparser = channels_parser.add_subparsers(dest="channels_command")
    channels_subparser.add_parser("generate-index", help="Generate index for a channel").add_argument(
        "channel_name", help="The name of the channel")
    channels_subparser.add_parser("get", help="Get the channel details from YouTube").add_argument(
        "channel_username", help="The username of the channel")
    channels_subparser.add_parser("ls", help="List all the channels in the cache")
    channels_subparser.add_parser(
        "report", help="Create a spreadsheet of videos for the given channels").add_argument(
            "channel_usernames", nargs="+")
    channels_subparser.add_parser("sync").add_argument("channel_names", nargs="+")
    channels_subparser.add_parser(
        "update", help="Obtain new information for channel from the YouTube API").add_argument(
            "channel_usernames", nargs="+")

    videos_parser = subparsers.add_parser("videos", help="Manage videos")
    videos_subparser = videos_parser.add_subparsers(dest="videos_command")
    download_parser = videos_subparser.add_parser("download", help="Download videos")
    download_parser.add_argument(
        "--channel-name", help="Download all videos for the given channel")
    download_parser.add_argument(
        "--mark-unlisted",
        action="store_true",
        help="Mark the video unlisted. The YouTube Data API does not contain that information.")
    download_parser.add_argument(
        "--skip-ids",
        type=str,
        help="A comma-separated list of video IDs to skip. Only applies to the --channel-name argument.")
    download_parser.add_argument(
        "--video-id", help="Download the video with the given ID and cache its info in the database")
    videos_subparser.add_parser(
        "get",
        help="Use the YouTube API to get and cache video information for a channel").add_argument(
            "channel_name", help="The name of the channel")
    ls_parser = videos_subparser.add_parser("ls", help="List all the videos in the cache")
    ls_parser.add_argument("channel_name", help="The name of the channel")
    ls_parser.add_argument(
        "--not-downloaded",
        action="store_true",
        help="Display only videos that haven't yet been downloaded")
    ls_parser.add_argument("--xls", action="store_true", help="Generate the list as a spreadsheet")

    playlists_parser = subparsers.add_parser("playlists", help="Manage playlists")
    playlists_subparser = playlists_parser.add_subparsers(dest="playlists_command")
    playlists_subparser.add_parser(
        "delete",
        help="Delete playlists for a channel").add_argument(
            "channel_name", help="The name of the channel")
    playlists_subparser.add_parser(
        "download",
        help="Download playlists for a channel").add_argument(
            "channel_name", help="The name of the channel")
    playlists_subparser.add_parser(
        "get",
        help="Get playlists for a channel").add_argument(
            "channel_name", help="The name of the channel")
    ls_playlist_parser = playlists_subparser.add_parser("ls", help="List playlists for a channel")
    ls_playlist_parser.add_argument("channel_name", help="The name of the channel")
    ls_playlist_parser.add_argument(
        "--add-unlisted",
        action="store_true",
        help="Add unlisted videos to the cache")
    ls_playlist_parser.add_argument(
        "--add-external",
        action="store_true",
        help="Add videos that are external to the channel to the cache")

    return parser.parse_args()


def main():
    api_key = os.getenv("YT_CH_ARCHIVER_API_KEY")
    if not api_key:
        raise Exception(
            "The YT_CH_ARCHIVER_API_KEY environment variable must be set with your API key"
        )
    args = get_args()
    youtube = build("youtube", "v3", developerKey=api_key)
    if args.command_group == "admin":
        if args.admin_command == "build-thumbnails":
            cmds.admin_build_thumbnails(args.channel_name)
        elif args.admin_command == "update-video-info":
            cmds.admin_update_video_info(args.channel_name)
        elif args.videos_command == "update-root-path":
            cmds.admin_update_root_path()
    elif args.command_group == "channels":
        if args.channels_command == "generate-index":
            cmds.channels_generate_index(args.channel_name)
        if args.channels_command == "get":
            cmds.channels_get(youtube, args.channel_username)
        elif args.channels_command == "ls":
            cmds.channels_ls()
        if args.channels_command == "report":
            cmds.channels_report(args.channel_usernames)
        elif args.channels_command == "sync":
            cmds.channels_sync(youtube, args.channel_names)
        if args.channels_command == "update":
            cmds.channels_update(youtube, args.channel_usernames)
    elif args.command_group == "videos":
        if args.videos_command == "download":
            skip_ids = []
            if args.skip_ids:
                skip_ids = args.skip_ids.split(",")
            cmds.videos_download(youtube, args.channel_name, skip_ids, args.video_id, False)
        elif args.videos_command == "get":
            cmds.videos_get(youtube, args.channel_name)
        elif args.videos_command == "ls":
            cmds.videos_ls(args.channel_name, args.not_downloaded, args.xls)
    elif args.command_group == "playlists":
        if args.playlists_command == "download":
            raise Exception("Not implemented yet")
        elif args.playlists_command == "get":
            cmds.playlists_get(youtube, args.channel_name)
        elif args.playlists_command == "ls":
            cmds.playlists_ls(args.channel_name, args.add_unlisted, args.add_external)
        elif args.playlists_command == "delete":
            cmds.playlists_delete(args.channel_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
