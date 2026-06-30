# Create Subscribers

This project didn't implement listeners so you need to manually add subscribers.

## Create a bot
First you need to create a bot. follow instructions on https://core.telegram.org/bots#6-botfather to create a bot.

## Get chat id
To find a chat_id, message the bot and open:

`https://api.telegram.org/bot<token>/getUpdates`

## Create a subscriber
For each subscriber, create subscribers/<name>.conf with:

```
[telegram]
token = <bot token from BotFather>
chat_id = <subscriber chat id>
```

Then add the subscriber name (without .conf) to telegram_subscriptions in the YAML config.
