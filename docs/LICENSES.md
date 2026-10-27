# Hyalune：ライセンスと依存資源

本プロジェクトで新規作成したSCSS・生成CSS・独自拡張・管理ツール・文書はMIT Licenseです。正本はルートの[LICENSE](../LICENSE)です。Copyright (c) 2026 Glass50 contributors。

LICENSEと既存ソースに記載された著作権表示を保持します。

| 対象 | 取扱い |
| --- | --- |
| `src/scss/`と生成CSS | 独自スタイル。MacTahoe / WhiteSurのコード・画像・アセットを取り込まない |
| `src/extension/`、`src/effects/` | 本プロジェクトの独自拡張・効果。MIT |
| 導入・ビルド・管理・検証ツール、文書 | 本プロジェクトの新規作成部分はMIT |
| 管理アプリアイコン `data/io.github.NBE03xxx.Hyalune.Settings.svg` | GNOME Tweaksアイコンの色変更版。GNOME Design Team、CC BY-SA 4.0。詳細は下記 |
| README紹介画像 | 本テーマを適用した専用環境での実際の画面。背景は紹介用に新規生成した画像。外部テーマの壁紙は転載しない。画面中のGNOME / アプリの表示・アイコン・商標の権利はそれぞれの権利者に帰属 |
| GNOME Shell、GTK、libadwaita、Adwaita | 導入済みシステムの資源を実行時に参照。コード・CSS・アイコンを本テーマのMITへ変更しない |
| User Themes | 別途導入する依存拡張。本リポジトリや配布パッケージに実装を同梱しない |
| Python3、PyGObject、GSettings、sassc | 実行・開発時依存。本プロジェクトのパッケージへ実装を同梱しない |
| Flatpakアプリとruntime | 別途配布される実行時依存。本リポジトリへ再配布しない |

[参考資料](../README.md#参考)は設計上の知見を得るために参照しました。外部テーマへの依存や、そのフォークを前提にしません。

外部コード・アセットを取り込む場合は、対象ファイル、取得元、版、著作権表示、ライセンス、変更内容をここに記録し、既存の条件を維持します。外部リポジトリのルートライセンスだけで、個別ファイルの条件を判断しません。

## 管理アプリのアイコン

`data/io.github.NBE03xxx.Hyalune.Settings.svg`は、GNOME Design Teamによる[GNOME Tweaks 49.0のアイコン](https://github.com/GNOME/gnome-tweaks/blob/80f792e2442fd072dac02de56000f445676b64cc/data/org.gnome.tweaks.svg)を基にした色変更版です。取得元は`GNOME/gnome-tweaks`、commit `80f792e2442fd072dac02de56000f445676b64cc`、ファイル`data/org.gnome.tweaks.svg`。原本のGit blobは`4c32beeef47ab9be4308be1752ab853ed3298f20`です。

原本SVG内の個別表示に従い、このアイコンとその改変は[Creative Commons Attribution-ShareAlike 4.0 International（CC BY-SA 4.0）](https://creativecommons.org/licenses/by-sa/4.0/)で提供します（[ライセンス全文](https://creativecommons.org/licenses/by-sa/4.0/legalcode.en)）。アプリ本体のMITとは別です。原本の作者・ライセンスをSVG内にも保持しています。

変更：2026年、Hyalune contributorsがスイッチの青`#3584e4`を青緑`#26a69a`、濃い青`#1a5fb4`を`#147d78`へ変更し、出典と変更内容を追記。形状・白い台座・無彩色部分は変更していません。GNOME Tweaks本体やシステムのアイコンを置き換えず、Hyalune専用のアプリIDで配置します。GNOMEによる推奨・公認を示すものではありません。

## GDMの導入先生成資源

独立GDMプレビューのコード・SCSS・overlayはMITです。導入先のGNOME / Ubuntu標準gresourceを読み取り、その環境だけで専用資源を生成します。配布用Gitソースに標準CSS・SVGのコピーは含みません。生成資源には、元のCSSにあるRed Hat / Intelの著作権・LGPL2.1等の表示を保持します。独自overlayのMIT表示で元資源全体の条件を置き換えません。生成資源を別途配布する場合は、元のgnome-shellパッケージに対応するソースと各ファイルのライセンス条件を個別に確認してください。

GDM初回取り込みの壁紙は、導入利用者の環境だけで管理用PNGへ変換・保存します。利用者の画像をGitソース・公開用exportへ収集しません。壁紙そのものの権利は元の権利者に帰属します。
