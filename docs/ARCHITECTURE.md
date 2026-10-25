# Hyalune：構成とコード

## 名称と内部識別名

正式名称はHyalune、現在のダーク版はHyalune Darkです。旧称Glass50 Dark / MyGlassから文書上の名称を変更しています。

既存の導入・更新・解除・復元との互換性を保つため、`Glass50-Material-Preview`、`glass50-blur@myglass.local`、`glass50`を含む配置先・設定schema・管理記録・CSSの識別子は維持しています。画像ファイル名や従来の生成物名も既存の参照先を継続使用します。表示される旧名は別テーマの導入を意味しません。今回の名称変更でコード・CSS・インストーラーの動作は変更していません。

## 入口と生成物

| 場所 | 役割 |
| --- | --- |
| `install.sh` | Git clone後の共通入口 |
| `tools/install-from-source.py` | 対象照合、導入用コード保存、基本テーマとFlatpakの一括導入・解除 |
| `src/scss/` | 色、透明度、角丸、境界線、影、余白と、Shell / GTK別スタイルの編集元 |
| `src/scss/material/` | 現行のガラス材質値・GTK4ウィンドウ・互換操作ボタンなど |
| `build/Glass50-Material-Preview/` | 導入に使う生成済みCSS。利用者は手編集しない |
| `src/extension/` | 独自拡張の入口・メタデータ・GSettings schema |
| `src/effects/` | 任意の背景ぼかし、角丸マスク、ウィンドウ背面と更新管理 |
| `tools/manage-material.py` | 材質テーマ・拡張の所有記録と変更計画 |
| `tools/manage-theme.py` | ファイルと設定のトランザクション・競合検知・逆順復旧 |
| `tools/desktop-context.py` | OS・実行中Shell・Wayland・通常ユーザーの共通照合 |
| `tools/manage-desktop.py` | GTK入口の保全・復元、共通runtime marker、旧管理記録の移行 |
| `tools/manage-t16.py` | 旧試用コードとの互換用。共通入口は旧記録を自動認識 |
| `tools/manage-flatpak.py` | アプリ単位のCSS・権限上書きの適用と復元 |
| `tools/flatpak-discovery.py` | アプリを実行しないGTK判定、管理記録のscan、一括導入・解除計画と復旧対象の照合 |

`build/Glass50-Dark/`と従来の基本管理ツールは以前の基本テーマ用です。現行の材質管理と識別を分けています。材質管理中に古い基本ツールで解除を代用しないでください。

## スタイル

Shell・GTK3・GTK4は別出力です。共通化するのはデザイン値と意味であり、同じCSSを全UIへ流用しません。`src/scss/material/_values.scss`が現行材質の主な編集元です。

Shellトップバーは暗い無彩色の38％面、標準GTK4クライアント装飾は同じ下地を使い、一般的な本文は重ね塗りで56％の面にします。文字・アイコン自体のopacityは下げません。アプリ固有の階層や追加CSSにより結果は変わります。

GTK4の一般パレットとクライアント装飾用`.csd`を分け、Chromeなどの色取得へネイティブ用の透明面が漏れないようにします。独立した互換タイトル面は暗い面を維持します。GTK由来の合成操作ボタンは色面16pxとし、通常のGTKボタンの操作領域を維持します。

GTK4 / libadwaitaはDark・通常コントラストの条件内で上書きします。Flatpak用出力は自己完結したCSSにし、ウィンドウ内ダイアログを不透明化します。

## 任意効果

`extension.js`がセッションと適用状態を確認し、Quick Settingsとウィンドウ材質の管理クラスを生成します。`runtime-context.js`はUbuntu 26.04・実行中Shell 50.x・Waylandとユーザー単位の適用markerを照合します。独立検証セッションは専用環境変数で区別します。ホスト名・CPU・GPU・固定ディスクは判定に使いません。

`window-backdrop-source.js`は対象ウィンドウの背面を組み立て、`rounded-background-blur.js`と`rounded-mask.js`が背景ぼかしと角丸を担当します。`refresh-gate.js`で背景更新を抑え、`window-material-commit.js`で対象の描画更新と同期します。前景の文字・アイコン・入力は元のウィンドウが担当します。

右クリックメニュー等の一時ポップアップの出入りでは既存のぼかしを保持します。GNOMEがネイティブ窓を並べ直す通知では、保持したぼかし層とアンカーを次の描画前に各窓の直下へ戻し、文字やアイコンを覆わないようにします。ポップアップの追加・削除時は、同じ層のまま有限回の背景更新を行い、閉じたメニューの位置に古い画素を残しません。ぼかし対象の通常ウィンドウ同士の順序が変わった場合は、背面の依存関係を組み直します。

無効化時には生成したActor・シグナル・タイマーを解放します。High Contrast / Reduced Motionや確認条件外では任意効果を停止します。外部のぼかし拡張や独自シェーダーを導入依存にはしません。

## 保全と復元

変更前後のファイルbytes・mode・設定のユーザー値と不在状態を記録します。所有記録に一致しない改変は停止し、無関係なCSSや設定を保持します。書き込み前にjournalを保存し、commit前の中断は逆順で復元します。commit後の中断は確定処理だけを完了します。同じ設定を複数段階で変更する場合も、各段階の状態を照合して初期値へ戻します。基本テーマとFlatpakで外観変更の共通ロックを使います。全体解除は管理記録をscanし、全対象の起動状態・CSS・権限・所有記録を検査してから一つのjournalへ計画します。途中失敗ではFlatpakも基本テーマも戻します。

新しい共通入口は`manage-desktop.py`を使い、GTK入口2ファイルの内容・リンクを保存して専用includeへ切り替えます。旧VMのimport形式と旧試用のリンク管理形式は所有記録から判別し、導入前の復元情報を保ったまま共通markerへ移行します。保存済みコードからの復旧でも中断journalから同じ形式を選びます。[条件と操作](INSTALL.md)

復旧用コピーは公開用ソースに含めません。設定・処理記録の削除とテーマの解除を混同しません。[操作方法](INSTALL.md)

## ビルド

SCSS編集時のみ`sassc`が必要です。

```sh
sh tools/build-material.sh
```

出力はShell、GTK3、GTK4 material、GTK4 FlatpakのCSSです。従来の基本テーマは`sh tools/build.sh`で生成します。schemaコンパイルはパッケージ組立時に行います。開発記録は配布ソースに含めず、利用者向け仕様をこの`docs/`へまとめます。
