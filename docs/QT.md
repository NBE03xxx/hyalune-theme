# Qtウィンドウボタン（任意プレビュー）

Ubuntu 26.04のGNOME Shell 50 / Waylandで、以下のアプリのタイトルバーに丸い閉じる・最大化／元に戻す・最小化ボタンを追加する部品です。固定サイズのウィンドウなど、元の装飾で利用できない操作は追加しません。

| 対象 | ビルドに必要なQt |
| --- | --- |
| Mozc設定ツール（ネイティブ） | 5.15.18 |
| Nextcloud Desktop（ネイティブ） | 6.10.2 |
| KeePassXC（Flatpak、KDE Platform 6.11） | 6.11.3 |

Hyalune系のShellテーマがUser Themesで有効な間だけ丸ボタンを描きます。別のShellテーマ、標準テーマ、High Contrast、User Themesの無効化では、起動中の対象ウィンドウも元のQt装飾に戻ります。「Hyalune 設定」での操作は不要です。GTKのアプリ外観とGDMのログイン画面は、それぞれの設定に従います。

導入には、対応するQtの開発用ヘッダー（privateヘッダーを含む）、対応するKDE SDKとruntime、C++コンパイラーが必要です。既存の開発環境でビルドし、生成物とソースを揃えてから、通常ユーザーで導入します。

```sh
python3 tools/build-qt.py \
  --flatpak-sdk-prefix /path/to/sdk/files \
  --flatpak-runtime-prefix /path/to/runtime/files
./install.sh qt plan
./install.sh qt install
./install.sh qt status
```

初回は対象アプリを完全終了してアプリ一覧から開き直します。既存のNextcloud自動起動も対象です。元のバイナリーを直接実行した場合は従来の起動環境を使います。Qtの版が対象外になった場合も従来の装飾で起動します。Flatpakの許可は対象の起動時にだけ渡します。

```sh
./install.sh qt plan --operation remove
./install.sh qt remove
```

中断時は先に `./install.sh qt recover` を実行します。元の起動ファイルの内容・モード・不在状態は `~/.local/state/hyalune/qt-installer-v1/` に保全します。通常テーマやGTK系Flatpakとは別管理です。既存ファイルの競合が検出された場合は上書き前に停止します。[実装とライセンス](../src/qt/README.md)
