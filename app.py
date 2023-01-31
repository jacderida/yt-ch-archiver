#!/usr/bin/env python

import os
import sqlite3
import sys

from googleapiclient.discovery import build


class Video:
    def __init__(self, id, title, is_downloaded):
        self.id = id
        self.title = title
        self.is_downloaded = is_downloaded

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
        is_downloaded = row[3]
        return Video(id, title, is_downloaded)


def main():
    api_key = os.getenv("YT_CH_ARCHIVER_API_KEY")
    channel_id = "UCtMf006J-WL-7r1T6guszjw"
    youtube = build("youtube", "v3", developerKey=api_key)
    (conn, cursor) = create_database()
    (channel_name, channel_is_cached) = get_channel_name(youtube, cursor, channel_id)

    videos = []
    print(f"Getting video list for {channel_name}")
    if channel_is_cached:
        print(f"Retrieving {channel_name} videos from cache...")
        cursor.execute("SELECT * FROM videos WHERE channel_id = ?", (channel_id,))
        rows = cursor.fetchall()
        for row in rows:
            video = Video.from_row(row)
            videos.append(video)
    else:
        print(f"{channel_name} is not cached. Will retrieve video list from YouTube...")
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


def get_channel_name(youtube, cursor, channel_id):
    print(f"channel_id: {channel_id}")
    cursor.execute("SELECT name FROM channels WHERE id = ?", (channel_id,))
    channel_name = cursor.fetchone()
    if channel_name:
        return (channel_name[0], True)
    channel_response = youtube.channels().list(part="snippet", id=channel_id).execute()
    channel_name = channel_response["items"][0]["snippet"]["title"]
    cursor.execute(
        """
    INSERT OR IGNORE INTO channels (id, name)
    VALUES (?, ?)
    """,
        (channel_id, channel_name),
    )
    return (channel_name, False)


def create_database():
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
        downloaded BOOLEAN DEFAULT 0,
        FOREIGN KEY (channel_id) REFERENCES channels (id)
    )
    """
    )
    return (conn, cursor)


if __name__ == "__main__":
    sys.exit(main())
