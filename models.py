from datetime import datetime
from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.text import Text
from rich.theme import Theme


class WordHighlighter(RegexHighlighter):
    base_style = "hl."
    highlights = [r"(?P<word_unlisted>UNLISTED)",
                 "(?P<word_external>EXTERNAL)"]


def print_video(video_id, title, is_unlisted, is_private, is_external, is_downloaded):
    theme = Theme({"hl.word_unlisted": "blue", "hl.word_external": "yellow"})
    console = Console(highlighter=WordHighlighter(), theme=theme)
    msg = f"{video_id}: {title}"
    if is_unlisted or is_private:
        msg += " ["
        if is_unlisted:
            msg += "UNLISTED, "
        if is_private:
            msg += "PRIVATE, "
        if is_external:
            msg += "EXTERNAL"
        msg = msg.removesuffix(", ")
        msg += "]"
    if is_downloaded:
        console.print(msg, style="green")
    else:
        console.print(msg, style="red")


class Video:
    def __init__(self, id, title, channel_id, saved_path, is_unlisted, is_private):
        self.id = id
        self.title = title
        self.channel_id = channel_id
        self.saved_path = saved_path
        self.is_unlisted = is_unlisted
        self.is_private = is_private
        self.download_error = ""

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
        is_downloaded = True if self.saved_path else False
        print_video(self.id, self.title, self.is_unlisted, self.is_private, False, is_downloaded)


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


class SyncReport:
    def __init__(self):
        self.start_time = datetime.now()
        self.videos_downloaded = {}
        self.failed_downloads = {}
        self.finish_time = None

    def _generate_report(self):
        report = []

        report.append("###############################################")
        report.append("#####                                     #####")
        report.append("#####               SYNC REPORT           #####")
        report.append("#####                                     #####")
        report.append("###############################################")
        report.append("Started: " + str(self.start_time))
        report.append("Finished: " + str(self.finish_time))
        
        report.append("\n################################")
        report.append("###### DOWNLOADED VIDEOS #######")
        report.append("################################")
        for channel, videos in self.videos_downloaded.items():
            small_banner = ""
            for _ in channel:
                small_banner += "="
            report.append(f"{small_banner}")
            report.append(f"{channel}")
            report.append(f"{small_banner}")
            for video in videos:
                report.append(f"{video.id}: {video.title}")

        report.append("\n############################")
        report.append("###### FAILED VIDEOS #######")
        report.append("############################")
        for channel, videos in self.failed_downloads.items():
            small_banner = ""
            for _ in channel:
                small_banner += "="
            report.append(f"{small_banner}")
            report.append(f"{channel}")
            report.append(f"{small_banner}")
            for video in videos:
                report.append(f"{video.id}: {video.title} -- {video.download_error}")
        return "\n".join(report)

    def print(self):
        print(self._generate_report())

    def save(self, file_path):
        with open(file_path, 'w') as file:
            file.write(self._generate_report())
