# Change Log

- 手動で更新しているので古いかもしれません...

## [Unreleased]

- 以下のURLで把握しています
  - <https://github.com/tetsuya-ki/discord-live-notificationbot/compare/main...develop>

### 機能追加

### 仕様変更

- fix: 定期確認時の添付を1回に削減 966a4b5290e2911d895a9e0b936eeab01df4c5bf
  - get_xxxの添付部分を削除
  - 更新件数をログに表示するよう変更
- add: YouTubeのxmlが取得できなかった時ログ出力 40d68deffb55eb0fc7baeba2453397ba27d1d640
- add: 配信通知の説明文を省略し、説明文省略の要否をコマンドで指定できるよう変更 b27a89552ce64dce0d2e1c6fba0eae861320d432
- fix: readの読み込み件数を修正(1,000件 -> 2,000件) 263989a8d40be9a8150384c65e2e89a3bdf95f94
- fix: タスクが多重起動しないように修正 194ca207c9b9280da1e57a14265124d26fc226ec
  - task_is_excutingがTrueの時、実行中。Falseの時は実行済
  - task_is_excutingがTrueの時は、他のタスクを起動しない
  - タスクの開始/終了をinfoログで出力させる
  - すでに起動が4回目の場合、次回から普通に動くようにする 839ddc24063381d490834cebbdfcd6a5ddaf1989
- fix: 無駄にギルド名ログに出力していた点を修正 fd44980221553dcdf6494fe698a6d44ab202d342

### バグ修正

- YouTube通知時の「謎の削除チェック」を一部変更 f095cfaaaae119c7ed5ad5f8c4a526ccb47e3b62
  - 「配信前が登録されていた場合は先に進む」という条件を削除
- ツイキャスのカテゴリなしに対応 55fae45b394c02a6fc6552611ba529f5ee085108
- fix #15 786b82513e45f96a6881c946899c8177be0c5e87
  - 誰も配信通知を登録していないライブについては確認しないよう修正
- fix #14 19e7894809518ae22d64b1c3b4c39647d1a0f5a8
  - YouTubeの最新動画がNoneの時は何もしない(チャンネルに動画が何もない等)

### その他

- CHANGELOG.mdを追加 0f92107bc57d31237fefd36f1cac5bdf1b0f8c2a

## [v0.7.0] - 2022-01-30

- commit: c4c2b64edc847ee061cbc3f9b20458fa2c2fdafa
- link: <https://github.com/tetsuya-ki/discord-live-notificationbot/releases/tag/v0.7.0>

### 機能追加(v0.7.0)

- fix #13  9089937c3f8a8a2ea4329e234ee5661de73875b6
  - URLで配信通知を登録できるよう仕様変更(今まで通りIDでも可能)
  - bugfix: ツイキャス登録時に誤って対応していないチャンネルIDと判定するバグを修正 710866108dea8ea0275579d8268a627f6e07fa5b
  - fix: ツイキャスについての些末な修正 a8bafbcb8dee761e6ebc3a88b0fc93fb084a668e
  - fix: ツイキャス通知時のメッセージを修正 b12d31ff371104249be3ccc2145283e4e9692def
  - fix: ツイキャスの配信通知登録・削除についてドキュメント追加 f5f93499e6fe3409a66c52830e5f67e97894a966

### 仕様変更(v0.7.0)

- ツイキャス配信通知対応に伴い、URLで配信通知を登録できるよう仕様変更(今まで通りIDでも可能)

### バグ修正(v0.7.0)

- YouTube取得のバグ修正 e4c675b9576250b29ebb978fe77f3bea856eaacc

### その他(v0.7.0)

- cogにdocstringを設定 fbf08702bf693d544057c402b1df375b34223543
- requestsを追加 301707aba81bd5702a927dc23ac59e5cd2c22424

## [0.6.0] - 2022-01-16

- commit: 2acfd1010e846d04c7476b4c9d49019fc604e454
- link: <https://github.com/tetsuya-ki/discord-live-notificationbot/releases/tag/v0.6.0>

### 機能追加(v0.6.0)

- フィルター文字列設定コマンドを追加 4d5c6b85bb05c0efdeaa0d1c9dab0d3a9e624bec
- fix #9 c133787099ddb90c73570d0ac17fe84ee92bbdc2

### 仕様変更(オプション追加含む)(v0.6.0)

- /live-notification_listにすべて表示するかどうかのオプション追加 7c7417162371400877e2b1c751fa00a4929657f4
- 動画名も記載するように変更 151b6c35fac0bde716a4698d59d294a41ac05c22
- fix #11 66a2e314a74527c65c646ebc6fc33a8ae0a8fd4b
- 動画名を記載するように変更 b7eb860c9e8e68b9fd9b934bd5ca519bc46566ec

### バグ修正(v0.6.0)

- fix #6 / 投稿メッセージが長すぎてエラーになりtaskが落ちるバグを修正 cc56eea23cf589f48efdabfcc6323f210dbe1a64
- 説明文が存在しない場合にエラーとなるバグを修正 3fda89ded10d01de7ee1c86a230743885522bd47
- fix #7 。リスト表示形式変更。削除に通知先チャンネルもオプション指定できるよう変更 25fac11697dd62cfb05039b19729da624aa3f550
- fix #10 cc8f50ba4c5abf5c7173f1c2a700c6f6c54b2301

### その他(v0.6.0)

- ライブラリのバージョンアップ a53296331afec569b0017043803af97b14fbe1bd
- 名詞の統一(ライブ通知→配信通知) b89860d03af85fc075ce0503f22339e03a00a4db
- README.mdに実装予定のコマンド(/set-filterword)を追加 88064cccb93dae96d5cda1423534a284e3a09544
- /live-notification_listの表示を少し変更(２列に変更)  f25e730ee04dd955a327b3ed8924552c3333f5ef
- live-notification_addがギルドコマンドになっていた問題を修正 fc49f9e822470b7c3d0eb2ab22ad9a84aa558f7b
- ユーザーとのDM作成処理をメソッドとして定義 3e78822a1a28c5edb1998217921cfaad8f68cbd7
- Merge branch 'develop' b59ae9092437c93e490f90193cebaaf411c145d4

## [0.5.0] - 2021-12-06

- commit: 49438f37cc18ce5ba14b65f5c4c6c203d314aa07
- link: <https://github.com/tetsuya-ki/discord-live-notificationbot/releases/tag/v0.5.0>
