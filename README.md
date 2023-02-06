# YouTube Channel Archiver

This is a simple utility that uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) and the [YouTube Data API](https://developers.google.com/youtube/v3/) to archive the contents of a YouTube channel.

It uses a SQLite database to cache channel information and avoid hitting the YouTube API as much as possible.

## Setup

You need to [obtain an API key](https://developers.google.com/youtube/registering_an_application) by registering an application, then you need to enable that application to use the YouTube Data API.

After you've obtained your key, assign it to the `YT_CH_ARCHIVER_API_KEY` environment variable.

Set a path for downloading the videos with the `YT_CH_ARCHIVER_ROOT_PATH` environment variable. Directories will be created under here that correspond to the name of each channel.

## Downloading Channel Videos

First get the list of all the videos for the channel by running this command:
```
./app.py list <channel-name>
```

Now get the ID of the channel either from the output of the previous command or by running:
```
./app.py list-channels
```

Now download them:
```
./app.py download <channel-id>
```

The utility will download the video, thumbnail, info and description for each video on the channel list. It configures `yt-dlp` to download the best mp4 video available, and failing that, the best video otherwise available.

The videos will be downloaded to `YT_CH_ARCHIVER_ROOT_PATH/channel_name/video`. By default `yt-dlp` uses the title of the video in the filename, but these can be huge and unwieldy. This utility just saves the video using the YouTube ID. For this reason, I added a command to generate a basic HTML file to function as an index, so it's easy to tell which video relates to which ID. Generate the index by running this command:
```
./app.py generate-index <channel-id>
```

This will output an `index.html` file at `YT_CH_ARCHIVER_ROOT_PATH/channel_name/video/index.html`.
