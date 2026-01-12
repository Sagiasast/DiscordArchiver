# discord-archive
Create local archive of a Discord server including visualization with HTML and local search

Goals:
- Definition of a scalable, browseable and searchable data file structure (e.g. based on HTML) to archive a discord server with multiple channels. If third party tools are needed to view the stored data, these should be open source
- Programming a bot which scans and automatically archives all the current data
- Programming a bot which adds the latest data to the archive (e.g. live, daily, weekly). This may be a configuration in the previous bot

Ideas:
- Use/adopt [Discard](https://github.com/Sanqui/discard) or [ChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) or some other tools
- Implement a Python script to transform the archive to HTML format
- HTML export using static browser pages, layout similar to Discord, channel list on the left, scrollable pages with messages on the right, auto-reloading. The HTML should be splitted into several pages for large channels.
- Search and filter box incl. date range, author, text string (with wildcards), based on a text file export of messages (without SQL etc.). A click on the search result should go to the archived HTML page
