# このBotについて

- Discordで配信通知をするBotです(ニコ生、YouTube、ツイキャスに対応)
- スラッシュコマンド（[goverfl0w / discord-py-slash-command](https://github.com/goverfl0w/discord-interactions)）が使えるため、コマンドを覚える必要がなく、それぞれのオプションの意味が表示されます
  - 何も設定していない(デフォルトの)場合、配信通知の説明文が30文字以降は省略されます。変更したい場合は[`/live-notification_set-filterword`](#/live-notification_set-filterword)のオプションで長く表示させることができます(チャンネル単位で指定は現在不可)
- 変更履歴は[tags](https://github.com/tetsuya-ki/discord-live-notificationbot/tags)か[CHANGELOG.md](/CHANGELOG.md)を確認ください

## 機能

### `/live-notification_add`

- 配信通知を登録します
- 必須のオプション(1つ)
  - live_channel_id(配信通知対象のチャンネルIDかURL)
    - ニコニコ生放送の場合は`coXXXXXX`の部分
      - coは省略可
      - または、コミュニティのURL: `https://com.nicovideo.jp/community/coXXXXXX`
    - YouTubeの場合は、`UCxxxxxxx`の部分
      - または、チャンネルのURL: `https://www.youtube.com/channel/UCxxxxxxx`
    - ツイキャスの場合は、`xxxxxxx`の部分
      - または、ユーザーページのURL: `https://twitcasting.tv/xxxxxxx`
- オプション
  - notification_chanel(通知チャンネル)
    - #xxxxで指定したチャンネルに配信通知します
    - そのままチャンネル名を指定することもできます
    - このオプションが**ない場合、コマンドを実行したチャンネルに配信通知します**
  - mention(メンション)
    - 通常のメッセージと同様に、@xxxx形式で入力してください（配信通知時にメンションされます）
      - `@here`, `@everyone`, `@username`等
  - reply_is_hidden
    - 自分のみ
      - 実行結果は自分だけ見ることができます
    - 全員に見せる
      - 実行結果はBotからのリプライとして表示されます

### `/live-notification_list`

- 配信通知を確認します
- オプション
  - disp_all_flag
    - すべて表示
      - 自分が登録した配信通知をすべて表示します(DMでは常にコチラが実行されます)
    - コマンドを実行するギルドへ登録した配信通知のみ表示(デフォルト)
      - コマンドを実行するギルドに自分が登録した配信通知のみ表示します
  - filter(配信通知リストを検索)
    - フィルタしたい文字列を入力すると、その文字列を含む配信通知のみ表示される
    - 例: ニコ生
      - ニコ生の配信通知のみ表示される
      - この例から分かる通り、配信通知に表示されている文字列を素朴に検索しているだけです
  - reply_is_hidden
    - 自分のみ
      - 実行結果は自分だけ見ることができます
    - 全員に見せる
      - 実行結果はBotからのリプライとして表示されます

### `/live-notification_delete`

- 配信通知を削除します
- 必須のオプション(1つ)
  - live_channel_id(配信通知対象のチャンネルID)
    - ニコニコ生放送の場合は`coXXXXXX`の部分
      - coは省略可
      - または、コミュニティのURL: `https://com.nicovideo.jp/community/coXXXXXX`
    - YouTubeの場合は、`UCxxxxxxx`の部分
      - または、チャンネルのURL: `https://www.youtube.com/channel/UCxxxxxxx`
    - ツイキャスの場合は、`xxxxxxx`の部分
      - または、ユーザーページのURL: `https://twitcasting.tv/xxxxxxx`
- オプション
  - notification_chanel(通知先チャンネルID)
    - 配信通知対象のチャンネルIDに加え、削除対象の通知先チャンネルを設定できます(#general等。「DM」でBotとのDMが削除対象になります)
    - 未指定の場合は通知先チャンネルかかわらず、コマンド実行者の配信通知チャンネルIDがすべて削除されます
  - reply_is_hidden
    - 自分のみ
      - 実行結果は自分だけ見ることができます
    - 全員に見せる
      - 実行結果はBotからのリプライとして表示されます

### `/live-notification_toggle`

- 配信通知のON/OFFを切り替えます
  - 配信通知したくない場合に実行します(一時的に通知しない場合などにオススメします)
- オプション
  - reply_is_hidden
    - 自分のみ
      - 実行結果は自分だけ見ることができます
    - 全員に見せる
      - 実行結果はBotからのリプライとして表示されます

### `/live-notification_set-filterword`

- フィルターする文字列(コンマ区切りで複数文字列設定可能)、説明文(長さ)を設定します
  - 新着配信があった際、通知しない動画の文字列を指定します
    - 動画タイトルと動画説明に、フィルター文字列が含まれている場合、Botはそれを通知しません
    - 個人ごとに設定されます(チャンネルごとへの設定はできません)
  - デフォルトの説明文(長さ)は30文字に制限されていますが、このコマンドで全文に変更できます
- オプション
  - filterword
    - 条件: 指定した場合
      - フィルターする文字列を設定します
      - 「,」のように指定することで、フィルターワードなしに変更できます
    - 条件: 未指定
      - 現在設定されているフィルターワードを表示します
  - is_long_description
    - 条件: 指定した場合
      - 説明文(長さ)を「長くする」「短くする(30文字以降省略)」のどちらかで設定できます(未設定は「短くする(30文字以降省略)」扱い)
    - 条件: 未指定
      - 現在設定されている説明文(長さ)を表示します
  - reply_is_hidden
    - 自分のみ
      - 実行結果は自分だけ見ることができます
    - 全員に見せる
      - 実行結果はBotからのリプライとして表示されます

### `/notification-task-check`

- BotのTaskが正常に動いているかチェックします(もし止まってたらTaskを開始します)
- オプション
  - reply_is_hidden
    - 自分のみ
      - 実行結果は自分だけ見ることができます
    - 全員に見せる
      - 実行結果はBotからのリプライとして表示されます

### その他のコマンドは検討中です

## 環境変数

### DISCORD_TOKEN

- 必須です。あなたのDiscordのトークンを記載（トークンは厳重に管理し、公開されないよう配慮すること！）
- 例: DISCORD_TOKEN="fdj2iur928u42q4u239858290"

### GUILD_ID_FOR_ATTACHMENTS

- 必須です。ファイルを添付するギルド(1件のみ指定してください)
- 例: GUILD_ID_FOR_ATTACHMENTS=99999999999

### LOG_LEVEL

- ログレベル(DEBUG/INFO/WARNING/ERROR)
- 例: LOG_LEVEL="INFO"

### ENABLE_SLASH_COMMAND_GUILD_ID_LIST(**使用するにはソースの修正が必要です**)

- この環境変数を使用する場合、ソースの修正をしてください
  - それぞれのメソッドにある、@cog_ext.cog_slashのguildsについてのコメントアウトを解除する必要があります
- スラッシュコマンドを有効にするギルドID(複数ある場合は「;」を間に挟むこと)
- 例
  - 1件の場合: ENABLE_SLASH_COMMAND_GUILD_ID_LIST=18471289371923
  - 2件の場合: ENABLE_SLASH_COMMAND_GUILD_ID_LIST=18471289371923;1389103890128390

### KEEP_DECRYPTED_FILE

- 復号されたファイルを残すかどうか(TRUEの時のみ残す。デフォルトでは復号されたファイルは削除される)
- 例: KEEP_DECRYPTED_FILE=FALSE

### IS_HEROKU

- Herokuで動かすかどうか
  - Herokuの場合、ファイルが削除されるので、discordの添付ファイルを使って保管を試みる(ファイルが削除されていたら、読み込む)
- 例: IS_HEROKU=FALSE

### IS_REPLIT

- Repl.itで動かすかどうか
  - Repl.itの場合、sqlite3の保管が怪しいので、discordの添付ファイルを使って保管を試みる
- 例: IS_REPLIT=TRUE

### RESTRICT_ATTACHMENT_FILE

- Bot自身が添付したファイルのみ読み込むように制限するかどうか
  - Bot以外(他のBotや人間)が添付したファイルのみを読み込むようになります
- 例: RESTRICT_ATTACHMENT_FILE=TRUE

## 動かし方

- wikiに書くつもりです(時期未定)
- わからないことがあれば[Discussions](https://github.com/tetsuya-ki/discord-live-notificationbot/discussions)に書いてみてください

### 前提

- poetryがインストールされていること
- `.env`が作成されていること

### 動かす

- 以下のコマンドを実行

```sh
poetry install
poetry run python discord-live-notificationbot.py
```
