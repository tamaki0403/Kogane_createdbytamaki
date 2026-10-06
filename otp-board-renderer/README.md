# Kogane OTP Board Renderer

Kogane OTP杯の大会状態JSONから、進行用PNGを生成するローカルCLIです。
現時点ではDiscord Bot本体とは分離し、予選4チームブロック画像を生成します。

## セットアップ

```bash
cd /Users/takemotomasaki/Documents/ChatGPT/Kogane/otp-board-renderer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install Pillow
```

## 使い方

```bash
python render.py
```

デフォルトでは以下を使います。

- 入力: `samples/sample_tournament.json`
- 設定: `configs/qualifier_4team.json`
- 出力: `output/qualifier_A.png`

任意のJSONや出力先を指定する場合:

```bash
python render.py \
  --input samples/sample_tournament.json \
  --config configs/qualifier_4team.json \
  --output output/qualifier_A.png
```

全ブロックのチーム一覧画像:

```bash
python render.py \
  --input samples/sample_overview.json \
  --config configs/qualifier_overview.json \
  --output output/qualifier_overview.png
```

トーナメント画像:

```bash
python render.py \
  --input samples/sample_bracket_tree.json \
  --config configs/bracket_tree.json \
  --output output/bracket_tree.png

python render.py \
  --input samples/sample_bracket_upper.json \
  --config configs/bracket.json \
  --output output/bracket_upper.png

python render.py \
  --input samples/sample_bracket_lower.json \
  --config configs/bracket.json \
  --output output/bracket_lower.png
```

## ディレクトリ

```text
otp-board-renderer/
  assets/
    templates/       # 差し替え用背景テンプレート
  configs/           # 座標、色、文字サイズなど
  samples/           # 入力サンプルJSON
  output/            # 生成PNG
  render.py
  README.md
```

`assets/templates/qualifier_4team.png` が存在する場合は背景として使います。
存在しない場合は、読みやすさ優先の仮背景を自動生成します。

## 入力データ案

Botから渡すデータは、レンダラー側ではDBやDiscordの事情を持たず、次のような表示用JSONに変換して渡す想定が扱いやすいです。

- `tournament_id`: 大会ID
- `updated_at`: 更新日時
- `block.block_id`: ブロックID
- `block.name`: ブロック名
- `block.teams`: 申請番号、チーム名、Bot計算済み順位、勝敗、本数
- `block.matches`: 試合番号、対戦チームID、スコア、状態、勝者ID

`matches` の各要素では、`match_no` を指定すると画像内に表示されます。
未指定の場合は `第1試合` のように自動表示します。

```json
{
  "match_id": "Q001",
  "match_no": "A-1",
  "teams": ["demo-20261006:OTP-001", "demo-20261006:OTP-002"],
  "score": [2, 1],
  "status": "done",
  "winner": "demo-20261006:OTP-001"
}
```

まだ行われていない試合は、`score` と `status` を省略できます。
その場合はスコア欄に `未入力` と表示し、進行状態ラベルは出しません。
勝者は `WINNER: ...` の文章ではなく、勝ったチーム名とスコアを強調表示します。
チーム欄は `rank` の昇順で描画します。

Bot組み込み時は、Bot本体が大会状態をこのJSON形式に整形し、以下のどちらかで連携できます。

1. Botが一時JSONを書き出し、`python render.py --input ... --output ...` をサブプロセス実行する
2. `render.py` の `render_board(data, config, output)` をPythonモジュールとして直接呼び出す

最初は1のサブプロセス方式が分離しやすく、Bot本体への影響も小さくできます。安定後に2へ移行すると、ファイルI/Oと起動コストを減らせます。

## 40チーム規模での更新方針

40チーム規模の大会で、全試合の `待機` / `進行中` / `終了` をリアルタイムにDiscordメッセージ更新し続ける運用は、手入力の負担と更新漏れが大きくなりやすいです。

おすすめは、終了した試合だけ結果を記録し、未実施の試合は未入力のままにする方式です。
Bot側には `画像更新` コマンドを用意し、主催者が必要なタイミングで実行して、最新の戦績からPNGを再生成・再投稿する形が現実的です。

将来的に自動化する場合も、まずは次の段階で十分です。

1. 結果入力コマンドでスコアと勝者だけ記録
2. 画像更新コマンドでPNGを再生成
3. 必要なら投稿済みメッセージを編集して画像を差し替え
4. 余裕が出たら `playing` などの進行状態を任意入力にする

## Botとの責務分担

レンダラーは計算しません。
Bot側で以下を確定してから、表示用JSONとして渡します。

- ブロック構成
- 予選順位
- 勝敗数、獲得本数、失った本数
- 上位/下位トーナメントの進出者
- トーナメントの配置、不戦勝、勝ち上がり先
- 各対戦のスコア、状態、勝者

レンダラー側は、渡された配置済みデータをPNGに描画するだけにします。
これにより、Bot再起動や画像再生成でトーナメント配置が変わる事故を防げます。

## 必要な画像タイプ

初期実装では `qualifier_block` と `qualifier_overview` に対応しています。
今後は同じ背景・配色でトーナメント画像を追加する想定です。

- `qualifier_block`: 各予選ブロックの進行画像。実装済み
- `qualifier_overview`: 全ブロックのチーム一覧画像。実装済み
- `bracket`: 上位/下位共通のトーナメント画像。実装済み
- `bracket_tree`: 一般的な横方向トーナメント表。実装済み

40チームの場合は `4チーム x 10ブロック` です。
各4チームブロックは1回総当たりなので、1ブロックあたり6対戦を表示します。
3チームブロックを追加する場合は、1ブロックあたり3対戦の別設定を用意します。

`qualifier_overview` はブロック数から列数を自動決定します。

- 10ブロック以下: 横2列
- 11〜15ブロック: 横3列
- 16ブロック以上: 横4列

64チームの場合は基本的に `4チーム x 16ブロック` なので、横4列で表示します。

## トーナメントJSON方針

20チームの上位/下位トーナメントは、32枠のシングルエリミネーションとしてBot側で配置済みJSONを渡します。
レンダラー側では再配置や不戦勝計算をしません。

- R1
- R2
- Quarterfinal
- Semifinal
- Final

不戦勝は試合結果として記録せず、Bot側で次ラウンドに配置済みとして渡します。
画像上では `status: "bye"` や `note: "不戦勝"` を見て補助表示します。

トーナメント画像は `configs/bracket_tree.json` を使う場合、一般的な横方向の表として描画します。
左から `R1 / R2 / QF / SF / Final` に進み、接続線は水平線と垂直線だけを使います。

`bracket_tree` の推奨入力は `rounds[].matches[].slots` です。
勝者判定、シード配置、不戦勝の自動計算、次ラウンド進出者の推測はしません。
R2以降の試合カードは、前ラウンド2試合の中央に自動配置します。

1試合は必ず2スロットです。

例:

- R1が16試合なら `matches` は16個
- R2が8試合なら `matches` は8個
- QFが4試合なら `matches` は4個
- SFが2試合なら `matches` は2個
- Finalが1試合なら `matches` は1個

`rounds[].matches[].slots` では、未確定枠は `team_key: null` にし、表示テキストは `note` に入れます。
例: `勝者待ち`、`未定`、`不戦勝`。

推奨フィールド:

- `rounds[].key`: `r1`、`r2`、`qf`、`sf`、`final`
- `rounds[].label`: 画像上のラウンド名
- `rounds[].bo`: そのラウンドのBO数。Finalは5、それ以外は3
- `matches[].match_key`: 試合識別子
- `matches[].label`: 画像上の試合名
- `matches[].slots`: 上側/下側の2枠
- `team_key`: チーム辞書参照用キー。未確定なら `null`
- `team_name`: チーム名。`teams` 辞書を使わず直接渡してもよい
- `entry_no`: 申請番号。画像上では `#1` のように表示
- `block`: 予選ブロック
- `rank`: 予選順位
- `score`: BO3/BO5の取得本数。未入力なら `null`
- `status`: `done`、`active`、`ready`、`waiting`、`bye` など
- `is_winner`: 勝った側だけ `true`
- `note`: `勝者待ち`、`不戦勝` などの補助表示

互換用として、古い `rounds[].slots` 形式も読み込めます。

## 複数画像の生成

このレンダラーは入力JSONと出力先を変えれば、複数ブロック画像を並行して生成できます。

```bash
python render.py --input samples/block_A.json --output output/qualifier_A.png
python render.py --input samples/block_B.json --output output/qualifier_B.png
```

Bot組み込み時は、A/B/C/DブロックのJSONを順に渡すだけでも十分高速です。
本当に必要になれば、Python側で複数プロセス実行にして同時生成できます。

## 拡張予定

- 予選3チーム用設定を追加
- 複数ブロックをまとめた画像または分割出力
- 上位トーナメント表レンダラー
- 下位トーナメント表レンダラー
- Discord投稿用のファイル名規則と再生成フロー
