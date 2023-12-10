import db
from models import Channel, Video, Playlist


def get_channel_info(youtube, channel_username):
    print("Retrieving channel information from YouTube...")
    request = youtube.channels().list(
        part="snippet", forUsername=channel_username
    )
    response = request.execute()
    if not "items" in response:
        print("Details not obtained via username query. Try obtaining by ID.")
        channel_id = get_channel_id_from_name(youtube, channel_username)
        request = youtube.channels().list(part="snippet", id=channel_id)
        response = request.execute()
    return Channel.from_channel_response_item(response["items"][0])


def get_channel_info_by_id(youtube, channel_id):
    print(f"Retrieving channel information for {channel_id} from YouTube...")
    request = youtube.channels().list(part="snippet", id=channel_id)
    response = request.execute()
    if not "items" in response:
        raise Exception(f"Channel with ID {channel_id} not found on YouTube")
    return Channel.from_channel_response_item(response["items"][0])


def get_channel_id_from_name(youtube, channel_name):
    request = youtube.search().list(
        part="snippet", type="channel", q=channel_name, maxResults=1
    )
    response = request.execute()
    if len(response["items"]) == 0:
        raise Exception(f"Could not obtain a channel ID for {channel_name}")
    channel_id = response["items"][0]["snippet"]["channelId"]
    print(f"The channel ID for {channel_name} is {channel_id}")
    return channel_id


def get_channel_videos(youtube, channel_id):
    videos = []
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
            videos.append(video)
        next_page_token = search_response.get("nextPageToken")
        if not next_page_token:
            break
    return videos


def get_playlists_for_channel(youtube, channel_id):
    playlists = []
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
            playlists.append(playlist)
        next_page_token = playlist_response.get("nextPageToken")
        if not next_page_token:
            break
    return playlists


def get_playlist_items(youtube, cursor, playlists, video_ids):
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
            playlist.add_item(
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


def get_video(youtube, cursor, video_id):
    print(f"Retrieving video info for {video_id} from YouTube...")
    request = youtube.videos().list(part="snippet", id=video_id)
    response = request.execute()
    response_items = response["items"]
    if len(response_items) == 0:
        raise Exception(f"Could not retrieve video with ID {video_id}")

    video_snippet = response_items[0]["snippet"]
    channel_id = video_snippet["channelId"]
    print(f"Video {video_id} has channel ID {channel_id}")
    channel = db.get_channel_by_id(cursor, channel_id)
    if channel:
        print(f"Channel ID {channel_id} is for {channel.title}")
        print(f"{channel.title} was already in the cache")
    else:
        print(f"Channel ID {channel_id} is not in the cache")
        channel = get_channel_info_by_id(youtube, channel_id)
    video = Video(video_id, video_snippet["title"], channel_id, "", False, False)
    return (video, channel)
