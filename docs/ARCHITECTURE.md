# Hyalune：構成とコード

## 名称と内部識別名

製品名はHyalune、外観はHyalune Dark／Hyalune Lightです。GNOME Shellの選択名と独自拡張の表示名は`Hyalune`で、Shellテーマ名は明暗共通です。

Shellの配置先は`~/.local/share/themes/Hyalune/gnome-shell/`です。GTKの内部配置名`Glass50-Material-Preview`、拡張UUID `glass50-blur@myglass.local`、schema・管理記録・CSSの識別子は既存導入との互換性のため保持します。生成物のディレクトリ名と、利用者がShellで選ぶ名前を区別します。

## 入口と生成物

| 場所 | 役割 |
| --- | --- |
| `install.sh`、`tools/install-from-source.py` | 共通の導入・更新・解除・復旧、初回Flatpak一括適用 |
| `src/scss/` | 色・透明度・角丸・境界・影・余白の編集元。ShellとGTKは別出力 |
| `src/scss/material/` | 共通の材質・GTK4ウィンドウ・互換操作ボタン |
| `src/scss/light/` | Light配色、アプリ文字、Shellの補正 |
| `build/Glass50-Material-Preview/` | 固定Darkの生成済みCSS |
| `build/Hyalune-Light/` | Lightの生成済みCSS |
| `src/extension/`、`src/effects/` | 自動明暗連動・アクセシビリティ退避・任意ぼかし |
| `src/manager/` | GTK4管理アプリ、型付きプロファイル、JSON API、Flatpak・GDM接続 |
| `tools/manage-material.py` | 素材と拡張の所有検査・計画、新旧Shell配置の移行 |
| `tools/manage-theme.py` | ファイルと設定のトランザクション・競合検知・逆順復旧 |
| `tools/manage-desktop.py` | GTK入口とリンクの保全・復元、runtime marker、既存所有形式の移行 |
| `tools/desktop-context.py` | OS・実行中Shell・Wayland・通常ユーザーの共通照合 |
| `tools/manage-flatpak.py`、`tools/flatpak-discovery.py` | GTK判定、アプリ単位CSS、管理一覧、一括保全・復旧 |
| `tools/manage-gdm.py`、`tools/install-gdm-helper.py` | 通常デスクトップと独立したGDM管理・認証窓口 |

`build/Glass50-Dark/`と基本テーマ専用ツールは、従来パッケージの復旧用に区別して保持します。現在の材質管理の解除を、この基本ツールで代用しません。[従来パッケージ](LEGACY-INSTALL.md)

## 素材とプロファイル

Shell・GTK3・GTK4で共通化するのはデザイン値と意味です。同じCSSをすべてへ流用しません。Darkは共通面56％／パネル38％、Lightは共通面78％／パネル74％を既定とし、管理アプリで編集できます。

GTK4は下地と内容面を重ねて共通面の不透明度へ合わせます。Dark既定では38％の下地と内容面を合わせて56％、Lightは74％の下地と内容面を合わせて78％です。文字・アイコンを含むウィンドウ全体のopacityは下げません。階層や独自CSSによる差はアプリごとに残ります。

GTK4の一般パレットと`.csd`のクライアント装飾を分け、Chrome等の色取得へ透明面が漏れないようにします。独立した互換タイトル面は暗い面を維持し、GTK由来の丸い操作ボタンは標準の操作領域を保持します。

形式3のプロファイルは`variant`、現在の`common`／`overrides`、反対側の`alternate`を持ちます。ぼかしとFlatpak政策は共通です。形式1／2の読取りとhashは維持し、単なる状態照会で書き換えません。

`src/manager/profile.py`は型を検証し、一時的なSCSS変数を使ってCSSを生成します。任意CSS・import・実行命令を設定として受け付けません。通常GTK4と管理Flatpakの形式3出力は明暗両方のmedia branchを含みます。[値と操作](LIGHT.md)

## 自動明暗連動と任意効果

`runtime-context.js`の`AppearanceSync`がGNOMEの`color-scheme`を監視し、配置済みmanagerの`sync`を呼びます。GUIの常時起動や独立したserviceは不要です。同期元は最後に適用した所有プロファイルで、未保存のGUI編集やGDMを消費しません。

Debounceと直列実行で連打をまとめ、ロック取得後にownerと明暗設定を再照合します。no-opは変更記録を増やしません。全体停止・個別停止・pending・外部競合を尊重し、自動コード更新は拒否します。詳細は[Light](LIGHT.md#連動が停止保留する場合)を参照してください。

`extension.js`は明暗監視とアクセシビリティ退避をぼかし選択と別に管理します。任意効果には`window-backdrop-source.js`、`rounded-background-blur.js`、`rounded-mask.js`、`refresh-gate.js`、`window-material-commit.js`を使います。前景の文字・アイコン・入力は元のウィンドウが描画します。

一時ポップアップの開閉では既存のぼかしを保持し、並び替え時は各窓の直下へ層を戻します。通常ウィンドウの前後関係が変わる場合は背面の依存関係を組み直します。Lightは背景明度1.0、Darkは0.85です。

High Contrast／Reduced Motion／条件外倍率では任意効果を停止します。無効化ではActor・signal・timerを解放し、新しい同期を予約しません。既に始まったtransactionは強制killせず回収します。実行時の照合はOS・Shell・Wayland・適用markerを使い、CPU・GPU・ホスト名を固定条件にしません。

## 外観の適用範囲

パネル、Quick Settings、通知、カレンダー、Overview、ポップアップ、切替一覧、OSD、GTKの主要面と丸い操作ボタンを調整します。`components/_end-session-dialog.scss`はログアウト・電源オフ・再起動の確認へ限定し、ボタン配置・警告・フォーカス・Escape・カウントダウンは標準実装を使います。面の値は選択中の素材に従います。

認証・権限・マウント・応答しないアプリ等の共通ダイアログ、ワークスペース切替表示、スクリーンショット操作部、画面キーボード、開発者ツールには専用の面調整を追加せず、GNOME標準表示を維持します。ユーザーセッションのロック画面も独立したテーマ対象へ広げません。GDMとは別の範囲です。

GTK4 Flatpakのアプリ内ダイアログは、背後の本文が重ならないよう不透明化します。LightのGTK3 FlatpakはHigh Contrastを優先して標準外観を使い、素材値は保持します。これらを未実装の漏れと扱いません。[対応アプリ](FLATPAK.md)

## 所有・保全・復元

変更前後のbytes・mode・設定のユーザー値と不在状態を保存します。所有状態と一致しない外部編集は停止し、無関係なCSSや設定を保持します。書込み前にjournalを保存し、commit前の中断は逆順で戻し、commit後の中断は完了処理を行います。

通常テーマと対応Flatpakは共有ロックと同じjournalを使います。一括解除では、起動状態・CSS・権限・所有記録を全体検査してから復元します。GDMと管理アプリ本体は別の所有・操作です。

GTK入口の内容・リンク・参照先bytesを保全し、リンク先の独立資産を変更しません。既存のimport形式・試用記録も所有情報から解釈し、元の復元情報を維持します。[条件と操作](INSTALL.md)

Shell配置の移行では、新旧の閉じた許可一覧を使い、旧Shellファイルをoriginalへ戻して新パスを登録します。移行後の所有には退役パスの欠落状態も含まれます。packageの実在16ファイルと、所有の最大17項目を区別します。古い限定形式のengineで新しいownerを操作しません。

保存sourceに`manager-base`がある場合、manager backendとアプリ導入は検証済みのそのbaseを使います。旧コードへ戻す際も、互換engine・保存payload・プロファイルをそろえます。コード更新の復帰をプロファイル用undoやowner単独コピーで代用しません。

## ビルドと公開ファイル

SCSSのビルドとプロファイルからの素材生成には`sassc`が必要です。固定の生成済みテーマの導入には不要です。

```sh
sh tools/build-material.sh
sh tools/build-light.sh
```

Darkは`build/Glass50-Material-Preview/`、Lightは`build/Hyalune-Light/`へ生成します。従来の基本テーマは`sh tools/build.sh`です。schemaはpackage組立時にコンパイルします。生成物を手編集しません。

利用者向け情報は`docs/`、ローカルの引き継ぎ・測定・環境保全は公開対象外の資料へ分けます。[公開ファイルの管理](PUBLISHING.md)
