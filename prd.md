# RedactSafe - Product Requirements Document

## Overview

**RedactSafe** は、行政機関の職員が安全かつ効率的にPDF文書の黒塗り（墨消し）処理を行うためのデスクトップアプリケーションである。

情報公開請求・開示請求への対応業務において、個人情報・機密情報を含む文書の一部を黒塗り処理したうえで開示する業務を支援する。「編集可能な仮マスキング（可逆）」と「不可逆な確定マスキング（完全削除）」の2段階設計により、実務フローへの適合と情報セキュリティの両立を実現する。

## Target Audience

| 利用者区分 | ロール | ITリテラシー |
|-----------|--------|-------------|
| 一般行政職員（担当者） | 編集者 | 中程度（Office操作可） |
| 管理職・決裁者 | 確認者 / 確定実行者 | 低〜中程度 |
| 情報システム担当 | 管理者 | 高い |

## Core Features

1. **PDF入出力** - 暗号化PDF・署名付きPDF対応、ドラッグ&ドロップ読込
2. **レイアウト解析・OCR** - PaddleOCR（主）/ Tesseract（補助）、デジタルPDFはテキスト抽出経路
3. **自動検出** - 正規表現 + MeCab形態素解析によるPII/機密情報検出、カスタムルール対応
4. **仮マスキング（Phase 1）** - UIオーバーレイによる編集可能な黒矩形、ON/OFF・移動・リサイズ・追加・削除
5. **確定マスキング（Phase 2）** - 300dpi画像化→黒塗り焼き込み→PDF再生成、hidden data完全除去
6. **状態管理・ロール制御** - draft/confirmed/finalized状態遷移、3ロール権限制御
7. **監査ログ** - JSON-Lines形式、ハッシュチェーンによる改ざん検知

## Tech Stack

- **デスクトップFW**: Tauri v2 (Rust)
- **フロントエンド**: Vanilla JS + HTML/CSS (WebView2)
- **PDF表示**: PDF.js
- **バックエンド**: Rust (Tauri Core) - ファイルIO、状態管理、ログ、IPC
- **OCR/処理**: Python (ローカルサブプロセス) - PaddleOCR, Tesseract, MeCab, Pillow, PyMuPDF
- **Python配布**: PyInstaller同梱 (standalone実行形式)
- **座標系**: PDF point (1pt = 1/72 inch) を正規座標
- **スタイリング**: カスタムCSS (Tailwind等のフレームワーク不使用)
- **認証**: なし (暫定: OSログイン名による本人識別)
- **ホスティング**: ローカルデスクトップアプリ (オフライン動作)

## Architecture

```
Tauri Desktop App
├── Frontend (Vanilla JS / WebView2)
│   ├── UIレンダリング
│   ├── 仮マスキングオーバーレイ (Canvas API)
│   ├── PDF表示 (PDF.js)
│   ├── ウォーターマーク
│   └── 状態表示・遷移UI
├── Rust Core (Tauri Backend)
│   ├── ファイルI/O
│   ├── 状態管理 (JSON)
│   ├── JS⇔Rust IPC (Tauri Command)
│   ├── Rust⇔Python IPC (stdin-stdout)
│   ├── ログ記録 (JSON-Lines)
│   └── セキュリティ検証
└── Python Worker (ローカルサブプロセス)
    ├── レイアウト解析 (PaddleOCR Layout)
    ├── 文字認識 (PaddleOCR / Tesseract)
    ├── bbox出力・座標変換
    ├── PII検出 (正規表現 + MeCab)
    ├── 確定マスキング処理 (Pillow / PyMuPDF)
    └── hidden data除去
```

### 処理フロー

```
[入力PDF]
  → [レイアウト解析] (PaddleOCR)
  → [文字認識] (PaddleOCR / テキスト抽出)
  → [bbox出力] (PDF point座標正規化)
  → [PII自動検出] (正規表現 + MeCab)
  → [仮マスキング生成] (UIオーバーレイ)
  → [ユーザー確認・修正] (ON/OFF・位置調整・手動追加)
  → [確認者承認] (confirmed状態)
  → [確定マスキング] (300dpi画像化→黒塗り焼き込み)
  → [hidden dataサニタイズ]
  → [安全PDF出力]
  → [ログ保存]
```

## Data Model

### マスキング設定ファイル (JSON)

```json
{
  "schema_version": "1.2",
  "document_id": "uuid-v4",
  "source_file": "path/to/file.pdf",
  "source_hash": "sha256:...",
  "status": "draft",
  "revision": 1,
  "confirmed_by": null,
  "finalized_by": null,
  "coordinate_system": { "unit": "pdf_point", "origin": "top-left", "dpi_for_rasterize": 300 },
  "history": [],
  "pages": [
    {
      "page": 1,
      "width_pt": 595.28,
      "height_pt": 841.89,
      "rotation_deg": 0,
      "text_extraction_path": "ocr",
      "regions": [
        {
          "id": "region-uuid",
          "bbox": [x, y, width, height],
          "type": "name",
          "confidence": 0.92,
          "enabled": true,
          "source": "auto",
          "note": ""
        }
      ]
    }
  ]
}
```

### ログファイル (JSON-Lines)

```json
{"timestamp": "...", "event": "file_opened", "user": "...", "prev_hash": "...", "data": {...}}
```

## UI/UX Requirements

- **レイアウト**: 左サイドバー（検出一覧パネル）+ 右メイン（PDFビューエリア）
- **警告バナー**: 「自動検出には漏れがある可能性があります。全ページを目視で確認してください」を常時表示
- **ウォーターマーク**: 「未確定 - 公開禁止」を半透明赤・45度斜めで表示
- **確定確認ダイアログ**: マスキング件数・対象ページ数を明示し「この操作は元に戻せません」警告
- **マスキング矩形表示**: 不透明黒(#000000)、選択時赤枠(#FF0000)、OFF時半透明グレー50%
- **アクセシビリティ**: フォントサイズ3段階、Tooltip、キーボード完結操作
- **キーボードショートカット**: 主要操作に割り当て、Ctrl+ZによるUndo

## Security Considerations

- **ローカル完結**: 全てのデータ処理をローカルで行い、外部ネットワークに送信しない
- **2段階マスキング**: 仮マスキングはPDF本体を変更せず、確定処理のみ不可逆処理
- **hidden data完全除去**: メタデータ、注釈、添付、フォーム、JS、ブックマーク、隠しレイヤー
- **状態遷移制約**: draft/confirmed状態ではファイル出力・印刷の全導線を無効化
- **ログ改ざん防止**: ハッシュチェーン方式、日次ルートハッシュの別保管
- **一時ファイル安全削除**: 処理完了後に確実に削除
- **座標精度**: bbox各辺に最低3ptマージン、受入基準±2pt以内

## Third-Party Integrations

なし（完全オフライン動作）。外部API・クラウドサービスへの接続は一切行わない。

## Constraints & Assumptions

- **対象OS**: Windows 10 / 11 (64bit) のみ
- **オフライン前提**: インターネット接続不要
- **低スペック対応**: Core i5 第8世代相当 / メモリ8GB ベースライン
- **メモリ制御**: 1ページずつ逐次処理、全ページ同時画像化禁止
- **PDFのみ入力**: 画像ファイル（JPEG/PNG等）の直接入力は不可
- **日本語前提**: 入力PDFは日本語文書を主対象
- **インストーラー**: MSI/EXE形式、WebView2ランタイム同梱、Python同梱

## Success Criteria

1. 安全PDFからテキスト抽出結果が0文字であること
2. PDFオブジェクト全走査でhidden dataが完全に除去されていること
3. OCR精度が標準300dpiで90%以上（CER ≦ 10%）
4. 自動検出のRecallが85%以上、False Positive Rateが20%以下
5. 座標精度が±2pt以内
6. 10ページ処理がOCR 60秒以内・確定処理30秒以内
7. 50ページPDFを10回連続処理でクラッシュなし
8. オフライン環境で全機能が動作

---

## Task List

```json
[
  {
    "category": "setup",
    "description": "Tauri v2プロジェクトの初期化とRust/JS/Pythonのディレクトリ構造を構築する",
    "steps": [
      "cargo create-tauri-app redact-safe --template vanilla を実行しTauri v2プロジェクトを作成",
      "プロジェクト構造を設定: src-tauri/ (Rust), src/ (Vanilla JS frontend), python-worker/ (Python)",
      "mise.tomlにRust toolchainを設定済みであることを確認",
      "cargo build でRustコアがコンパイル可能であることを確認",
      "npm install でフロントエンド開発環境が動作することを確認"
    ],
    "passes": true
  },
  {
    "category": "setup",
    "description": "Pythonワーカーの依存関係を設定し、基本的なstdin/stdout通信を確立する",
    "steps": [
      "python-worker/ ディレクトリを作成しrequirements.txtを配置（PyMuPDF, Pillow, PaddleOCR, MeCab, pyyaml）",
      "Pythonワーカーのエントリポイント worker.py を作成し、stdin/stdoutベースのJSON-RPC通信プロトコルを実装",
      "Rust側からPythonワーカープロセスを起動しpingコマンドで通信確認するTauriコマンドを実装",
      "フロントエンドからRust経由でPythonワーカーにpingを送り応答を確認するテストUIを作成",
      "dev serverを起動して通信が確立されていることをブラウザで確認"
    ],
    "passes": true
  },
  {
    "category": "setup",
    "description": "JSON-Lines形式のロギングシステムとハッシュチェーンを実装する",
    "steps": [
      "Rust側にJSON-Linesログ出力モジュールを実装（ローテーション対応）",
      "各ログレコードに前レコードのSHA-256ハッシュを含めるハッシュチェーンを実装",
      "日次ルートハッシュを別ファイルに保存する機能を実装",
      "ログ保存先を %APPDATA%/RedactSafe/logs/ に設定",
      "Tauriコマンド経由でログ記録を呼び出せるようにする"
    ],
    "passes": true
  },
  {
    "category": "setup",
    "description": "JSONベースの状態管理システムと座標系ユーティリティを実装する",
    "steps": [
      "Rust側にマスキング設定ファイル（JSON）のCRUD操作モジュールを実装",
      "schema_version, document_id, source_hash, status, pages等のデータ構造を定義",
      "状態遷移ロジック（draft→confirmed→finalized）をRust側に実装",
      "Python側に座標変換ユーティリティ（PDF point ↔ pixel）を実装",
      "ページ回転補正関数（0°/90°/180°/270°）をPython側に実装",
      "座標変換の単体テストを作成し正確性を確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "PDF.jsによるPDFビューアーとマルチページナビゲーションを実装する",
    "steps": [
      "PDF.jsをフロントエンドに導入しTauri WebView内でPDFをレンダリング",
      "ページ切替UI（前ページ/次ページボタン、ページ番号表示）を実装",
      "ページのズームイン/ズームアウト機能を実装",
      "PDF.jsのレンダリング座標系とアプリのPDF point座標系の対応を確認",
      "10ページのテストPDFでページ切替が正常動作することを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "ファイル入力機能（ファイルピッカー・ドラッグ&ドロップ・暗号化PDF・署名付きPDF）を実装する",
    "steps": [
      "ファイルメニューからPDFファイルを選択するファイルピッカーを実装",
      "ドラッグ&ドロップによるPDF読込を実装",
      "暗号化PDF検出時にパスワード入力ダイアログを表示する機能を実装",
      "署名付きPDF検出時に警告ダイアログを表示する機能を実装",
      "PyMuPDFでPDFメタデータ（暗号化・署名の有無）を検出するPythonワーカー機能を実装",
      "PDF読込時にログ記録（file_openedイベント）されることを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "PaddleOCRによるレイアウト解析・文字認識パイプラインを実装する",
    "steps": [
      "PythonワーカーにPaddleOCR Layout Analysis統合を実装",
      "各ページを領域（段落・表・図・ヘッダ）に分類する機能を実装",
      "分類結果をJSON形式で出力する機能を実装",
      "PaddleOCR文字認識モジュールによるテキスト・bbox抽出を実装",
      "信頼スコア < 0.5 の場合にTesseractフォールバックする機能を実装",
      "テストスキャンPDF（300dpi）でレイアウト解析・OCR結果を確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "デジタルネイティブPDFのテキスト抽出経路（PyMuPDF）を実装する",
    "steps": [
      "PyMuPDFで各ページのテキストレイヤー有無を判定する機能を実装",
      "テキストが存在する場合は文字クワッド（character quad）からbboxを取得する機能を実装",
      "テキスト抽出経路のconfidenceを1.0固定とする",
      "テキスト抽出失敗時はOCR経路にフォールバックする処理を実装",
      "デジタルPDFのテストファイルでテキスト抽出が正常動作することを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "bbox出力の正規化（座標変換・行統合・回転補正）を実装する",
    "steps": [
      "OCR結果のピクセル座標をPDF point座標に変換する機能を実装",
      "近接するbboxを行単位でグルーピングし最小外接矩形で統合する機能を実装",
      "ページ回転（90°/180°/270°）に対するbbox回転補正を実装",
      "bbox統合後の結果がJSON形式で正しく出力されることを確認",
      "回転付きテストPDFで回転補正が正しく動作することを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "正規表現によるPII自動検出エンジンを実装する",
    "steps": [
      "住所検出（都道府県〜番地パターン）の正規表現を実装",
      "電話番号検出（市外局番パターン）の正規表現を実装",
      "マイナンバー検出（12桁数字）の正規表現を実装",
      "メールアドレス検出（RFC準拠パターン）の正規表現を実装",
      "生年月日検出（和暦・西暦両対応）の正規表現を実装",
      "法人番号検出（13桁数字）の正規表現を実装",
      "デフォルト検出ルールをYAMLファイルとして定義・読込を実装",
      "テストテキストで各検出パターンの動作を確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "MeCabによる氏名検出とカスタム検出ルールシステムを実装する",
    "steps": [
      "MeCab + UniDicの形態素解析による氏名（固有名詞）検出を実装",
      "検出結果に検出種別・信頼スコアを付与する機能を実装",
      "カスタム検出ルール（YAML/JSON）の読込・スキーマ検証を実装",
      "正規表現の安全性チェック（catastrophic backtracking検出）を実装",
      "本体同梱ルールとカスタムルールのファイル分離を実装",
      "テストテキストで氏名検出が動作することを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "OCR・検出処理のプログレス表示を実装する",
    "steps": [
      "Pythonワーカーからページ単位の進捗をIPC経由でフロントエンドに通知する機能を実装",
      "フロントエンドにプログレスバー（全体進捗の百分率表示）を実装",
      "10秒以上更新がない場合に「処理が停止している可能性があります」を表示する機能を実装",
      "キャンセルボタンからキャンセル要求→1秒以内にUIが反応することを確認",
      "OCR処理がバックグラウンドスレッドで実行されUIスレッドをブロックしないことを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "OCR・検出処理のプログレス表示を実装する（重複）",
    "steps": [
      "Pythonワーカーからページ単位の進捗をIPC経由でフロントエンドに通知する機能を実装",
      "フロントエンドにプログレスバー（全体進捗の百分率表示）を実装",
      "10秒以上更新がない場合に「処理が停止している可能性があります」を表示する機能を実装",
      "キャンセルボタンからキャンセル要求→1秒以内にUIが反応することを確認",
      "OCR処理がバックグラウンドスレッドで実行されUIスレッドをブロックしないことを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "仮マスキングオーバーレイエンジン（Canvas API）を実装する",
    "steps": [
      "PDFビューア上にCanvas APIでオーバーレイレイヤーを重ねる機能を実装",
      "自動検出結果のbbox位置に黒矩形(#000000)を描画する機能を実装",
      "マスキング矩形の選択時に赤枠(#FF0000)で強調表示する機能を実装",
      "OFF時の矩形を半透明グレー(50%)で表示する機能を実装",
      "自動検出（青枠）と手動追加（緑枠）の色分け表示を実装",
      "PDF表示座標とマスキング座標の同期が正しいことを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "マスキング矩形の操作（ON/OFF・移動・リサイズ・追加・削除）を実装する",
    "steps": [
      "各マスキング箇所のON/OFFトグル切替を実装",
      "マスキング矩形のドラッグによる位置変更を実装",
      "マスキング矩形のドラッグによるサイズ変更を実装",
      "ユーザーによる手動マスキング矩形の追加機能を実装",
      "マスキング箇所の削除機能を実装",
      "全操作のCtrl+Z Undo対応を実装",
      "操作のたびにJSON自動保存・操作ログ記録されることを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "検出一覧サイドバーパネル・一括操作・フィルタリング・ウォーターマークを実装する",
    "steps": [
      "左サイドバーに検出一覧パネルを実装（検出件数・種別表示）",
      "検出種別（PII種別）によるフィルタリング表示を実装",
      "全マスキング箇所の一括ON・一括OFF機能を実装",
      "draft/confirmed状態のPDFビューに「未確定 - 公開禁止」ウォーターマークを表示（半透明赤、45度斜め）",
      "サイドバーの検出項目クリックで該当箇所にスクロール・ハイライトする機能を実装",
      "ウォーターマークがfinalized状態で消滅することを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "ドキュメント状態管理（draft/confirmed/finalized）と状態遷移制約を実装する",
    "steps": [
      "ドキュメントの3状態（draft/confirmed/finalized）遷移ロジックをRust側に実装",
      "draft/confirmed状態でファイル出力・印刷の全導線をアプリレベルで無効化",
      "draft/confirmed状態でドラッグ&ドロップによる外部ファイルドロップを無効化",
      "confirmed状態では編集操作を無効化（確認者は差し戻しのみ可能）",
      "finalized状態では安全PDFのファイルパスのみ公開し元PDFのパスは非公開",
      "状態遷移時にログ記録されることを確認"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "操作者識別・確認承認フロー・差し戻し機能を実装する",
    "steps": [
      "OSログイン名をデフォルト識別子として取得する機能を実装",
      "確認承認時に操作者名の再入力ダイアログを表示する機能を実装",
      "再入力された操作者名をOSログイン名と共に監査ログ・設定ファイルに記録",
      "確認者による差し戻し（confirmed→draft）機能を実装",
      "差し戻し後も直前の承認履歴がhistoryに残存することを確認",
      "編集者と確定実行者のOSログイン名が同一の場合に警告を表示する機能を実装",
      "confirmed_by/finalized_byにOSログイン名、display名を併記する機能を実装"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "確定マスキング処理（300dpi画像化→黒塗り焼き込み→PDF再生成）を実装する",
    "steps": [
      "確定実行者がconfirmed状態でのみ「確定して出力」ボタンを押下可能にする",
      "確定処理前の確認ダイアログ（マスキング件数・対象ページ数・警告）を実装",
      "各ページを300dpiで逐次ラスタライズ（1ページずつ、全ページ同時禁止）する機能を実装",
      "黒色矩形をbbox+最低3ptマージンで焼き込む機能（Pillow）を実装",
      "焼き込み後の画像をPNG圧縮（FlateDecode）でPDFページとしてバッファに追加（PyMuPDF）",
      "画像メモリを解放してから次ページへ進む逐次パイプライン処理を実装",
      "出力ファイル名規則 <元ファイル名>_redacted_<YYYYMMDD_HHMMSS>_r<revision>.pdf を実装",
      "同名ファイル存在時の自動採番（_r2, _r3...）を実装"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "hidden dataサニタイズと確定後検証を実装する",
    "steps": [
      "メタデータ（XMP・DocInfo辞書）の完全除去を実装",
      "注釈（Annotations）の除去を実装",
      "添付ファイル（EmbeddedFiles）の除去を実装",
      "フォームフィールド（AcroForm/XFA）の除去を実装",
      "JavaScriptアクション（OpenAction/AA）の除去を実装",
      "ブックマーク（Outlines）の除去を実装",
      "隠しレイヤー（OCProperties）の除去を実装",
      "コピー禁止パーミッション設定を実装",
      "出力後にPyMuPDFでPDFオブジェクト全走査による検証を実装（テキスト不在、hidden data不在の確認）",
      "検証失敗時は出力PDFを破棄しエラーとして中断する機能を実装"
    ],
    "passes": false
  },
  {
    "category": "feature",
    "description": "一時ファイル安全削除・自動保存・バックアップシステムを実装する",
    "steps": [
      "確定処理中の一時ファイル（画像化中間ファイル等）を完了後に安全削除する機能を実装",
      "仮マスキング設定の自動保存機能を実装（定期的・操作時）",
      "アプリクラッシュ時の設定ファイル自動回復機能を実装",
      "設定ファイルの直近3世代バックアップ保持機能を実装",
      "ログファイルに元の個人情報テキストを含めない（region_id・bbox・typeのみ）ことを確認"
    ],
    "passes": false
  },
  {
    "category": "feature",
    "description": "警告バナー・設定ダイアログ・キーボードショートカット・アクセシビリティを実装する",
    "steps": [
      "PDFビューエリア上部に「自動検出には漏れがある可能性があります。全ページを目視で確認してください」警告バナーを常時表示",
      "警告バナーをdraft/confirmed状態のみ表示し、finalizedで非表示にする",
      "警告バナーを閉じる(dismiss)操作を無効とする",
      "設定ダイアログ（フォントサイズ：標準/大/特大、圧縮方式：PNG/JPEG、JPEG品質下限85%）を実装",
      "主要操作のキーボードショートカットを割り当て",
      "主要ボタンにTooltipを表示",
      "キーボードのみで全操作が完結できることを確認"
    ],
    "passes": false
  },
  {
    "category": "feature",
    "description": "メインウィンドウレイアウトとUI全体の統合・ポリッシュを行う",
    "steps": [
      "メニューバー（[ファイル] [設定] [ヘルプ]）を実装",
      "メインレイアウト（左サイドバー + 右PDFビューエリア + 下部ツールバー）を実装",
      "下部ツールバーに [全てON] [全てOFF] モード表示 [確定して出力] を配置",
      "ステータスバーにドキュメント状態（draft/confirmed/finalized）を表示",
      "ウィンドウリサイズに応じたレイアウト調整を実装",
      "全体のUIが要件定義書の画面構成図に合致することを確認"
    ],
    "passes": false
  },
  {
    "category": "integration",
    "description": "デジタルPDFのエンドツーエンドワークフローを検証する",
    "steps": [
      "デジタルネイティブPDF（テストセットC: 10ページ日本語+英数字混在）を用意",
      "ファイル読込→テキスト抽出経路→bbox取得→自動検出→仮マスキング表示までの動作を確認",
      "マスキングON/OFF・移動・追加・削除の全操作をテスト",
      "確認承認→確定処理→安全PDF出力までの全流れを実行",
      "出力PDFでテキスト抽出が0文字であることを確認",
      "出力PDFでhidden dataが完全除去されていることを確認",
      "座標精度が±2pt以内であることを確認",
      "ログに全イベントが正しく記録されていることを確認"
    ],
    "passes": false
  },
  {
    "category": "integration",
    "description": "スキャンPDFのエンドツーエンドワークフローを検証する",
    "steps": [
      "スキャンPDF（テストセットA: 300dpi 10ページ日本語）を用意",
      "ファイル読込→OCR経路→bbox取得→自動検出→仮マスキング表示までの動作を確認",
      "マスキング編集操作をテスト",
      "確認承認→確定処理→安全PDF出力までの全流れを実行",
      "OCR精度（文字単位正答率90%以上）を確認",
      "自動検出のRecall 85%以上、FPR 20%以下を確認",
      "10ページの確定処理が30秒以内に完了することを確認",
      "出力PDFのテキスト不在・hidden data完全除去を確認"
    ],
    "passes": false
  },
  {
    "category": "integration",
    "description": "暗号化PDF・署名付きPDFの特殊ケースワークフローを検証する",
    "steps": [
      "暗号化PDF（テストセットE）でパスワード入力→復号→通常処理を確認",
      "誤パスワード入力で定型エラーメッセージが表示されることを確認",
      "署名付きPDF（テストセットF）で署名検出→警告ダイアログ→処理継続を確認",
      "処理後の安全PDFからデジタル署名が除去されていることを確認",
      "キャンセル選択で読み込みが中止されることを確認"
    ],
    "passes": false
  },
  {
    "category": "integration",
    "description": "状態遷移制約・ロール権限・監査ログの統合テストを実行する",
    "steps": [
      "draft状態でファイル出力・印刷が全導線で無効化されていることを確認",
      "confirmed状態でマスキング編集がブロックされることを確認",
      "差し戻し（confirmed→draft）後も承認履歴が残存することを確認",
      "同一文書を同日に2回処理して異なるファイル名で出力されることを確認",
      "ログのハッシュチェーンが正しく構築され改ざん検知が動作することを確認",
      "日次ルートハッシュが別ファイルに保存されることを確認",
      "50ページPDFを10回連続処理してクラッシュが発生しないことを確認"
    ],
    "passes": false
  },
  {
    "category": "packaging",
    "description": "PyInstallerによるPythonワーカーのバンドルとWindowsインストーラーを作成する",
    "steps": [
      "PyInstallerでPythonワーカーをstandalone実行形式にバンドル",
      "バンドルされたPythonワーカーがTauriアプリから正常に起動することを確認",
      "Tauriのビルド設定でWindows向けインストーラー（MSI/EXE）を構成",
      "WebView2ランタイムのオフラインインストーラーを同梱する設定",
      "インストーラーでWebView2自動セットアップが動作することを確認",
      "クリーンなWindows環境でインストール→起動→基本操作が動作することを確認"
    ],
    "passes": false
  }
]
```

---

## Agent Instructions

1. Read `activity.md` first to understand current state
2. Find next task with `"passes": false`
3. Complete all steps for that task
4. Verify in browser using agent-browser
5. Update task to `"passes": true`
6. Log completion in `activity.md`
7. Repeat until all tasks pass

**Important:** Only modify the `passes` field. Do not remove or rewrite tasks.

---

## Completion Criteria

All tasks marked with `"passes": true`
