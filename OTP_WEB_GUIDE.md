# Kogane OTP杯 Web連携（ローカル確認版）

本変更は閲覧専用です。Railwayへの反映、本番Botの再起動、本番データの変更、Discordへの投稿は行っていません。

## 既存実装の調査結果

### 1. 実装済みで、そのまま利用する処理

- 大会ID別の保存: `get_otp_tournaments` / `save_otp_tournaments`。`bot_state.json`へ一時ファイル置換で保存され、起動時に`load_bot_state`で復元される。
- 登録: `process_otp_demo_bulk_message`、`parse_otp_demo_bulk_text`、`validate_otp_demo_team`。キーは`大会ID + 申請番号`、申請番号と数値部分を別保存する。
- 組分け・予選対戦: `calculate_otp_demo_blocks`、`make_round_robin_matches`。3または4チーム組の総当たり。
- チェックイン: `OTPMatchCheckinView`。対戦につき一度、両チーム分が揃ってから報告UIを出す。
- 結果確定: `OTPMatchReportView` / `otp_demo_report_win`。両リーダーの同一報告か`otp_demo_judge`による裁定だけが`otp_demo_record_battle_result`へ入る。
- 予選順位・進出先: `rank_otp_demo_block`、`maybe_finish_qualifiers_and_build_brackets`。勝利数、本数、失本、2チーム同率時の直接対決、申請順を使う。
- 大会開始・終了: `start_otp_demo_tournament`、`otp_demo_finish`。
- Discord IDなしのテスト登録: `build_otp_solo_test_team` / `start_otp_solo_test`。

### 2. 部分実装で、補完が必要な処理

- 本戦: `build_single_elim_bracket`は初戦と不戦枠を保存するが、初戦勝者を次ラウンドへ反映する処理、2回戦以降の対戦生成、大会の自動完了はない。
- 不戦勝: 架空対戦・架空スコアを作らず`slots` / `auto_advancers`で保持する点は利用できる。一方、次ラウンドの実対戦へ接続する処理はない。
- 再起動復元: 大会データ自体は復元されるが、`on_ready`でOTPの対戦報告・チェックイン・操作パネルViewを再登録していない。テキストコマンドによる復旧経路はある。
- 公開画像: 表示用JSONとPNG生成はあるが、確定時の自動更新ではなく`OTP画像更新`による手動更新。

### 3. 未実装の処理

- OTP大会結果の訂正・巻き戻し。既存の`undo_result`は通常レート戦用でOTP大会とは別。
- 本戦2回戦以降の生成・勝ち上がり。
- 開始後の棄権・失格処理。

### 4. コードだけでは判断できない仕様

- 3チーム以上が完全同率の場合の最終ルール（現状は申請順）。
- 開始後の棄権・失格が順位、本数、対戦済み結果へ与える影響。
- 4チーム未満の組から何チームを上位へ進めるか（現状の3チーム組も上位2チーム）。
- 本戦の具体的なシード配置規則。現状は乱数で不戦枠を選ぶ。

## 追加したWeb連携

- `otp_web.py`: 既存大会状態を公開用JSONへ変換する薄い層。順位関数はBotと共用し、Webでは再計算しない。
- `GET /api/otp/tournaments`: 公開可能な大会一覧。
- `GET /api/otp/tournaments/{tournament_id}`: 1大会の一貫したスナップショット。
- `web/static/otp.html`: 確認済みHTMLのDOM・CSSを復元した閲覧ページ。元HTMLとの差はインライン仮データを外部スクリプト読込へ置き換えた箇所だけ。
- `web/static/otp.js`: 元HTMLの仮データ生成を、公開JSONの取得・描画へ置き換える連携層。元HTMLの5列トーナメント、カード、接続線、リーグ切替を使う。

公開JSONからDiscord ID、報告者ID、運営ID、チャンネルID、片側報告の内容を除外する。片側報告や不一致時は`winner_team_id`と確定スコアを返さない。外部入力はDOMへ入れる前にHTMLエスケープする。

WebはServer-Sent Eventsで`bot_state.json`の置換保存通知を受け、変更時だけ大会単位のJSONを再取得する。接続断への保険として60秒ごとの再取得も行う。APIは`Cache-Control: no-store`で返すため、古い順位と新しい対戦表を別々に取得しない。読み込み中、データなし、取得失敗を区別し、取得失敗時に仮データへ切り替えない。

## フォーム申請プレビューとDiscord大会の連携

`all-teams-layout-test`を本番進行の表示として使う大会は、開始前に次を実行する。

```text
!OTPWeb連携 大会ID
```

連携後は、Web申請一覧（テスト回答の申請番号1・2を除く）とDiscord大会の参加可能チームについて、申請番号が完全一致しなければ大会を開始しない。完全一致した場合だけ、Webプレビューと同じ保存済み抽選キーから同じ予選組を作り、Discordの大会データへ確定保存する。開始後の`all-teams-layout-test` APIは、そのDiscord大会データを返すため、結果・順位・本戦も同一データから表示される。

ページ再読込やチーム名変更では再抽選しない。新規フォーム申請時だけ抽選キーを更新する。大会開始後は確定済みの`blocks`を使い、新しい申請によって進行中の組分けを変更しない。

## ローカル起動

Botが保存した状態を読む場合（リポジトリ直下から実行）:

```bash
OTP_BOT_STATE_FILE=/data/bot_state.json uvicorn web.main:app --host 127.0.0.1 --port 8765
```

ブラウザで次を開く:

```text
http://127.0.0.1:8765/otp.html?tournament_id=大会ID
```

`tournament_id`を省略した場合は、更新日時が最も新しい大会を表示する。ローカルの別ファイルを使う場合は`OTP_BOT_STATE_FILE`にその絶対パスを指定する。

## テスト

```bash
python3 -m unittest discover -s tests -v
```

このテストは40チームの3/2/3/2表示、配置番号順、上下リーグ分離、片側報告の非確定扱い、Discord IDなしチーム、非公開IDの除外を確認する。
