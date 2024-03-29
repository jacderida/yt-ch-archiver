import db
import glob
import os
import urllib.parse
import yt
import yt_dlp


from bs4 import BeautifulSoup
from datetime import datetime
from models import VideoDownloadReport, SyncReport, Video, VideoListSpreadsheet
from pathlib import Path
from PIL import Image
from pymediainfo import MediaInfo


# According to the yt-dlp documentation, this format selection will get the
# best mp4 video available, or failing that, the best video otherwise available.
FORMAT_SELECTION = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b"


#
# Admin Commands
#
def admin_build_thumbnails(channel_name):
    download_root_path = os.getenv("YT_CH_ARCHIVER_ROOT_PATH")
    if not download_root_path:
        raise Exception(
            "The YT_CH_ARCHIVER_ROOT_PATH environment variable must be set"
        )
    input_images_path = Path(download_root_path).joinpath(channel_name).joinpath("video")
    output_thumbnails_path = input_images_path.parent.joinpath("thumbnail")

    print(f"Using {input_images_path} as the input directory.")
    print(f"Using {output_thumbnails_path} as the output directory.")

    if not os.path.exists(output_thumbnails_path):
        os.makedirs(output_thumbnails_path)
    for filename in os.listdir(input_images_path):
        if filename.endswith('.jpg') or filename.endswith('.webp'):
            input_path = os.path.join(input_images_path, filename)
            if filename.endswith('.webp'):
                output_filename = os.path.splitext(filename)[0] + '.jpg'
            else:
                output_filename = filename
            output_path = os.path.join(output_thumbnails_path, output_filename)
            # It's possible the thumbnail was already generated from a previous run
            # so don't bother doing it again.
            if not os.path.exists(output_path):
                create_thumbnail(input_path, output_path)


def admin_update_video_info(channel_name):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_name)
    videos = db.get_videos(cursor, channel_id, False)
    videos_len = len(videos)
    for i, video in enumerate(videos):
        print(f"Processing video {i + 1} of {videos_len}")
        if video.saved_path:
            (duration, resolution) = get_media_info(video.saved_path)
            video.duration = duration
            video.resolution = resolution
            db.save_downloaded_video_details(cursor, video)
    conn.commit()
    cursor.close()
    conn.close()


def admin_update_video_root_path():
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
        current_path = Path(video.saved_path)
        current_root_path = Path(video.saved_path).parent.parent.parent
        if download_root_path != current_root_path:
            new_path = download_root_path.joinpath(
                channels[video.channel_id]).joinpath("video").joinpath(current_path.name)
            db.save_video_path(cursor, str(new_path), video.id)
    conn.commit()
    cursor.close()
    conn.close()


def admin_update_video_saved_path():
    (conn, cursor) = db.create_or_get_conn()
    videos = db.get_downloaded_videos(cursor)
    channels = db.get_channels(cursor)
    for video in videos:
        new_path = get_channel_download_path(channels[video.channel_id])
        new_path = new_path.joinpath("video")
        new_path = new_path.joinpath(f"{video.id}.mp4")
        db.save_video_path(cursor, str(new_path), video.id)
    conn.commit()
    cursor.close()
    conn.close()


#
# Channel Commands
#
def channels_delete(channel_username):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_username)
    videos = db.get_videos(cursor, channel_id, False)

    print(f"Channel {channel_username} has ID {channel_id}")
    print(f"This channel has {len(videos)} videos in the cache")
    user_input = input(f"Are you sure you want to delete? (y/n): ")
    if user_input.lower() != 'y':
        print("Channel deletion cancelled")
        return

    try:
        conn.execute('BEGIN')
        channel_id = db.get_channel_id_from_username(cursor, channel_username)
        db.delete_playlists(cursor, channel_id)
        db.delete_videos(cursor, channel_id)
        db.delete_channel(cursor, channel_id)
        conn.commit()
        print(f"Channel {channel_username} deleted")
    except Exception as e:
        conn.rollback()
        print(f"An error occurred: {e}")
    finally:
        cursor.close()
        conn.close()


def channels_generate_index(channel_name):
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


def channels_get(youtube, channel_username):
    channel = yt.get_channel_info(youtube, channel_username)
    (conn, cursor) = db.create_or_get_conn()
    db.save_channel_details(cursor, channel)
    conn.commit()
    cursor.close()
    conn.close()


def channels_info(username, id):
    (conn, cursor) = db.create_or_get_conn()
    if id:
        channel = db.get_channel_by_id(cursor, id)
        if not channel:
            raise Exception(f"Channel with ID {id} is not in the cache")
    elif username:
        channel = db.get_channel_by_username(cursor, username)
        if not channel:
            raise Exception(f"Channel with username {username} is not in the cache")
    else:
        raise Exception("Either the --id or --username arguments must be supplied")
    cursor.close()
    conn.close()
    print(f"ID: {channel.id}")
    print(f"Username: {channel.username}")
    print(f"Title: {channel.title}")


def channels_ls():
    (conn, cursor) = db.create_or_get_conn()
    channels = db.get_all_channel_info(cursor)
    for channel in channels:
        print(f"{channel.id}: {channel.username} -- {channel.title}")
    cursor.close()
    conn.close()


def channels_report(channel_names):
    report_data = {}
    (conn, cursor) = db.create_or_get_conn()
    for channel_name in channel_names:
        print(f"Retrieving data for {channel_name}...")
        channel_id = db.get_channel_id_from_username(cursor, channel_name)
        videos = db.get_videos(cursor, channel_id, False)
        report_data[channel_name] = videos
    cursor.close()
    conn.close()
    report = VideoListSpreadsheet()
    report.generate_report(report_data, "videos.xlsx")


def channels_sync(youtube, channel_names):
    report = SyncReport()
    for channel_name in channel_names:
        videos_get(youtube, channel_name)
        playlists_get(youtube, channel_name)
        (downloaded_videos, failed_videos) = download_videos_for_channel(channel_name, [])
        report.videos_downloaded[channel_name] = downloaded_videos
        report.failed_downloads[channel_name] = failed_videos
    report.finish_time = datetime.now()
    report.print()
    report.save("report.txt")


def channels_update(youtube, channel_names):
    (conn, cursor) = db.create_or_get_conn()
    if channel_names:
        for channel_name in channel_names:
            channel = yt.get_channel_info(youtube, channel_name)
            db.save_updated_channel_details(cursor, channel)
            conn.commit()
        cursor.close()
        conn.close()
        return
    print("Updating channel information for all cached channels")
    channels = db.get_all_channel_info(cursor)
    channel_count = len(channels)
    for i, channel in enumerate(channels):
        try:
            print(f"Processing channel {i + 1} of {channel_count}")
            current_channel_info = yt.get_channel_info_by_id(youtube, channel.id)
            db.save_updated_channel_details(cursor, current_channel_info)
            conn.commit()
        except Exception as e:
            print(f"Failed to update {channel.id}:")
            print(e)
            continue
    cursor.close()
    conn.close()


#
# Video Commands
#
def videos_download(youtube, channel_username, skip_ids, video_id, mark_unlisted, path):
    if channel_username:
        report = VideoDownloadReport() # created here to establish a start time for the process
        (downloaded_videos, failed_videos) = download_videos_for_channel(channel_username, skip_ids)
        report.mark_finished()
        report.add_data_sources(downloaded_videos, failed_videos)
        report.print()
        report.save("video_download.log")
    elif video_id:
        (conn, cursor) = db.create_or_get_conn()
        try:
            video = db.get_video_by_id(cursor, video_id)
            if video:
                if video.saved_path:
                    print(f"Video with ID {video_id} has already been downloaded")
                    print(f"Title: {video.title}")
                    print(f"Saved to: {video.saved_path}")
                    return
                else:
                    print(f"Video {video_id} was already in the cache but has not been saved")
                    channel = db.get_channel_by_id(cursor, video.channel_id)
                    if not channel:
                        raise Exception(f"Channel with ID {video.channel_id} is not in the cache")
                    print(f"Video relates to channel {channel.username} with ID {channel.id}")
                    download_videos([video], [], { channel.id: channel.username })
            else:
                (video, channel) = yt.get_video(youtube, cursor, video_id)
                if mark_unlisted:
                    video.is_unlisted = True
                db.save_channel_details(cursor, channel)
                db.save_video(cursor, video)
                download_videos([video], [], { channel.id: channel.username })
        finally:
            conn.commit()
            cursor.close()
            conn.close()
    elif path:
        video_ids = []

        with open(path, "r") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            parsed_url = urllib.parse.urlparse(line)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            if "v" in query_params:
                video_id = query_params["v"][0]
                video_ids.append(video_id)

        (conn, cursor) = db.create_or_get_conn()
        videos_to_download = []
        for video_id in video_ids:
            add_video_to_download_list_or_ignore(youtube, cursor, video_id, videos_to_download)

        # Videos in this file can relate to any channel, so we need the whole channel table.
        channel_id_name_table = db.get_channels(cursor)
        conn.commit()
        cursor.close()
        conn.close()
        download_videos_for_multiple_channels(
            videos_to_download, channel_id_name_table, "path_download.log")


def videos_get(youtube, channel_name):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = yt.get_channel_id_from_name(youtube, channel_name)
    db.save_channel(cursor, channel_id, channel_name)
    videos = yt.get_channel_videos(youtube, channel_id)
    for video in videos:
        db.save_video(cursor, video)
    conn.commit()
    cursor.close()
    conn.close()


def videos_ls(channel_name, not_downloaded, use_xls):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_name)
    print(f"{channel_id}")
    videos = db.get_videos(cursor, channel_id, not_downloaded)
    if use_xls:
        report = VideoListSpreadsheet()
        report.generate_report(videos, "videos.xslx")
    else:
        for video in videos:
            video.print()
    cursor.close()
    conn.close()


#
# Playlist Commands
#
def playlists_ls(channel_name, add_unlisted, add_external):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_name)
    playlists = db.get_playlists(cursor, channel_id)
    for playlist in playlists:
        db.get_playlist_items(cursor, playlist)
        playlist.print_title()
        for item in playlist.items:
            video = db.get_video_by_id(cursor, item.video_id)
            item.print(video)
            if add_unlisted:
                if item.is_unlisted and not item.is_private and not item.is_deleted:
                    db.save_video(cursor, Video.from_playlist_item(item))
            if add_external:
                if item.is_external:
                    db.save_video(cursor, Video.from_playlist_item(item))
    conn.commit()
    cursor.close()
    conn.close()


def playlists_get(youtube, channel_name):
    print(f"Getting playlists {channel_name} from YouTube")
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_name)
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


def playlists_delete(channel_name):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_name)
    db.delete_playlists(cursor, channel_id)
    conn.commit()
    cursor.close()
    conn.close()
    print(f"Deleted playlists for {channel_name}")


def playlists_download(youtube, channel_username, playlist_title):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_username)
    playlists = db.get_playlists(cursor, channel_id)
    videos_to_download = []

    if playlist_title:
        playlists = [x for x in playlists if x.title == playlist_title]
        if len(playlists) == 0:
            raise Exception(f"Channel {channel_username} has no playlist named {playlist_title}")
    for playlist in playlists:
        db.get_playlist_items(cursor, playlist)
        for item in playlist.items:
            add_video_to_download_list_or_ignore(youtube, cursor, item.video_id, videos_to_download)
    # Playlists can have items which are videos that are external to the
    # channel where the playlist is defined. Therefore, the entire channel list
    # needs to be retrieved to be passed to the video downloading function,
    # which needs the channel username to save the video to the correct
    # location.
    channel_id_name_table = db.get_channels(cursor)
    conn.commit()
    cursor.close()
    conn.close()
    download_videos_for_multiple_channels(
        videos_to_download, channel_id_name_table, "playlist_download.log")


#
# Helpers
#
def get_videos_for_channel(channel_username):
    (conn, cursor) = db.create_or_get_conn()
    channel_id = db.get_channel_id_from_username(cursor, channel_username)
    videos = db.get_videos(cursor, channel_id, False)
    cursor.close()
    conn.close()
    return (videos, { channel_id: channel_username })


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


"""
Create a thumbnail of 150x150.

However, the size of the input image varies, and the aspect ratio of the input image is respected.
To keep every thumbnail the same size, the resized input image will be placed in another 150x150
'container' image which will have transparent pixels.
"""
def create_thumbnail(input_path, output_path):
    desired_size = (150, 150)
    img = Image.open(input_path)
    
    ratio = min(desired_size[0] / img.width, desired_size[1] / img.height)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    img_resized = img.resize(new_size, resample=Image.Resampling.LANCZOS)
    
    # Create new blank image and paste the resized one in the center
    new_img = Image.new("RGB", desired_size, (0, 0, 0))  # black background
    new_img.paste(img_resized, ((desired_size[0] - new_size[0]) // 2, 
                                (desired_size[1] - new_size[1]) // 2))
    print(f"Saving thumbnail to {output_path}...")
    new_img.save(output_path, "JPEG")


def get_media_info(video_path):
    print(f"Reading media info from {video_path}")
    media_info = MediaInfo.parse(video_path)
    video_track = next(track for track in media_info.tracks if track.track_type == "Video")
    minutes, milliseconds = divmod(video_track.duration, 60 * 1000)
    seconds = milliseconds // 1000
    duration = f"{minutes}m{seconds}s"
    resolution = f"{video_track.width}x{video_track.height}"
    return (duration, resolution)


def download_videos_for_channel(channel_username, skip_ids):
    (videos, channel_id_name_table) = get_videos_for_channel(channel_username)
    print(f"Attempting to download videos for {channel_username}...")
    return download_videos(videos, skip_ids, channel_id_name_table)


def download_videos(videos, skip_ids, channel_id_name_table):
    downloaded_videos = []
    failed_videos = []
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
        channel_download_path = get_channel_download_path(channel_id_name_table[video.channel_id])
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
                "home": os.path.join(channel_download_path, "video"),
                "description": os.path.join(channel_download_path, "description"),
                "infojson": os.path.join(channel_download_path, "info"),
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
                video.saved_path = get_full_video_path(
                    os.path.join(channel_download_path, "video"), video.id
                )
                (duration, resolution) = get_media_info(video.saved_path)
                video.duration = duration
                video.resolution = resolution

                (conn, cursor) = db.create_or_get_conn()
                db.save_downloaded_video_details(cursor, video)
                conn.commit()
                cursor.close()
                conn.close()

                video_path = Path(video.saved_path)
                thumb_dir_path = video_path.parent.parent.joinpath("thumbnail")
                if not os.path.exists(thumb_dir_path):
                    os.makedirs(thumb_dir_path)

                thumb_input_path = video_path.parent.joinpath(video.id + ".webp")
                if not thumb_input_path.exists():
                    # If the thumbnail is not in .webp, try .jpg.
                    print(f"Thumbnail not detected at {thumb_input_path}")
                    thumb_input_path = video_path.parent.joinpath(video.id + ".jpg")
                    print(f"Will try {thumb_input_path} instead")
                if thumb_input_path.exists():
                    thumb_output_path = thumb_dir_path.joinpath(video.id + ".jpg")
                    create_thumbnail(thumb_input_path, thumb_output_path)
                else:
                    print(f"No webp or jpg thumbnail detected for {video.id}")

                downloaded_videos.append(video)
            except Exception as e:
                print(f"Failed to download {video.id}:")
                print(e)
                (conn, cursor) = db.create_or_get_conn()
                video.download_error = str(e)
                db.save_download_error(cursor, video.id, str(e))
                conn.commit()
                cursor.close()
                conn.close()
                failed_videos.append(video)
                continue
    return (downloaded_videos, failed_videos)


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


def get_channel_download_path(channel_username):
    if channel_username[0] == '@':
        channel_username = channel_username[1:] # strip the @ from the username
    download_root_path = os.getenv("YT_CH_ARCHIVER_ROOT_PATH")
    if not download_root_path:
        raise Exception(
            "The YT_CH_ARCHIVER_ROOT_PATH environment variable must be set"
        )
    download_path = os.path.join(download_root_path, channel_username)
    return Path(download_path)


def add_video_to_download_list_or_ignore(youtube, cursor, video_id, videos_to_download):
    video = db.get_video_by_id(cursor, video_id)
    if video:
        if not video.saved_path:
            print(f"Adding video with ID {video.id} to download list")
            videos_to_download.append(video)
        else:
            # Even though the video has a saved path set, it could be possible
            # that it was deleted unintentionally, so check that it actually
            # has been saved. If it hasn't, it will be downloaded again.
            if not os.path.exists(video.saved_path):
                print(f"Adding video with ID {video.id} to download list")
                videos_to_download.append(video)
            else:
                print(f"Video with ID {video.id} has already been downloaded")
    else:
        try:
            print(f"Video with ID {video_id} was not in the cache")
            (video, channel) = yt.get_video(youtube, cursor, video_id)
            db.save_video(cursor, video)
            db.save_channel_details(cursor, channel)
            print(f"Adding video with ID {video.id} to download list")
            videos_to_download.append(video)
        except Exception:
            print(f"Could not retrieve {video_id}")
            print(f"It will not be added to the download list")


def download_videos_for_multiple_channels(videos_to_download, channel_id_name_table, report_file_name):
    report = VideoDownloadReport() # created here to establish a start time for the process
    (downloaded_videos, failed_videos) = download_videos(videos_to_download, [], channel_id_name_table)
    report.mark_finished()
    report.add_data_sources(downloaded_videos, failed_videos)
    report.print()
    report.save(report_file_name)
