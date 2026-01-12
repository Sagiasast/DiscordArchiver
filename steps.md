# Setup Bot via Discord 
https://discord.com/developers/applications/

## Create the bot in the Discord Developer Portal

    1. Go to the Discord Developer Portal → Applications → New Application.
    2. Give it a name (e.g., ArchiverBot).
    3. In the left sidebar, open Bot → click Add Bot.

### Get the bot token

    1. In Bot → Reset Token / Copy Token.
    2. Keep it secret. If lost regenerate


## Enable the required intents


    In Bot settings:
    1. Turn ON Message Content Intent
    2. Turn ON Server Members Intent 


## Invite the bot to your server (connect it to the server)


    1. Developer Portal → OAuth2 → URL Generator

    2. Under Scopes, check:
        ✅ bot

    3. Under Bot Permissions, check at minimum:
        ✅ View Channels
        ✅ Read Message History
        ✅ Send Messages 
        ✅ Embed Links 

    4. Copy the generated URL at the bottom and open it in your browser.
    5. Pick your server and authorize.



# Run the bot 

## General
    python3 discord_archiver.py <BOT_TOKEN> [update_interval_hours] [archive_path]


- python3 discord_archiver.py YOUR_BOT_TOKEN

    Disable auto-archiving:
    - python3 discord_archiver.py YOUR_BOT_TOKEN 0

- Change interval to every 6 hours and archive to a custom folder:
    - python3 discord_archiver.py YOUR_BOT_TOKEN 6 ./my_archive

### Use it inside discord 

- In any channel the bot can read & write, run:

    ### Full archive:
       !archive_full

    ### Incremental update (only new messages since last run):
        !archive_update
    ### Status:
        !archive_status

    
