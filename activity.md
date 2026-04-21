# RedactSafe - Activity Log

## Current Status
**Last Updated:** 2026-04-21
**Tasks Completed:** 14 / 25
**Current Task:** Task 14 - マスキング矩形の操作（ON/OFF・移動・リサイズ・追加・削除）を実装する (完了)

---

## Session Log

### 2026-04-21 - Task 1: Tauri v2プロジェクト初期化とディレクトリ構造構築

**変更内容:**
- `npm init` で package.json 作成
- Vite v8.0.9 + @tauri-apps/cli v2.10.1 + @tauri-apps/api インストール
- `npx tauri init` で src-tauri/ (Rust backend) を初期化
- src/ (Vanilla JS frontend) に index.html, main.js, styles.css 作成
- python-worker/ ディレクトリ作成
- tauri.conf.json: identifier を com.redactsafe.app に設定、ウィンドウサイズ 1200x800 に調整
- vite.config.js: Tauri dev サーバー設定 (port 1420)
- .gitignore: dist/, target/ を追加

**実行コマンド:**
- `npm install -D vite @tauri-apps/cli@latest` - 成功
- `npm install @tauri-apps/api@latest` - 成功
- `npx tauri init` - 成功
- `cargo check` (src-tauri/) - 成功 (507 crates, 1m09s)
- `npm run build` - 成功 (dist/ にビルド出力)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** なし

### 2026-04-21 - Task 2: Pythonワーカーの依存関係設定とstdin/stdout通信確立

**変更内容:**
- `python-worker/requirements.txt` 作成（PyMuPDF, Pillow, paddleocr, paddlepaddle, fugashi, unidic-lite, pyyaml）
- `python-worker/worker.py` 作成 - stdin/stdoutベースのJSON-RPC 2.0通信プロトコル実装
  - `ping` コマンド: メッセージのエコー応答
  - `get_version` コマンド: ワーカー バージョンと利用可能メソッド一覧
  - エラーハンドリング: JSON parse error, method not found, internal error
- `src-tauri/src/python_worker.rs` 作成 - Pythonワーカープロセス管理モジュール
  - Pythonパス自動検出（python3/python/py順）
  - worker.pyパス解決（dev/production両対応）
  - JSON-RPCリクエスト送受信（stdin/stdout）
  - プロセス生存確認・kill機能
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `init_worker`: Pythonワーカープロセス起動
  - `shutdown_worker`: ワーカー終了
  - `worker_ping`: ping送信
  - `worker_get_status`: ワーカー接続状態確認
- `src-tauri/Cargo.toml` 更新 - tauri-plugin-shell, uuid 追加
- `src-tauri/capabilities/default.json` 更新 - shell権限追加
- `index.html` 更新 - Python Workerテストパネル追加（Initialize Worker / Send Ping）
- `src/styles.css` 更新 - テストパネルUIスタイル追加
- `src/main.js` 更新 - ワーカー初期化・ping通信のロジック実装

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (warningなし)
- `cargo clippy` (src-tauri/) - 成功 (warningなし)
- `npm run build` - 成功 (dist/ にビルド出力)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonがシステムにインストールされていないため、実際のワーカー通信テストは未実施。Python環境導入後に実行時テストが必要。

### 2026-04-21 - Task 3: JSON-Lines形式のロギングシステムとハッシュチェーン

**変更内容:**
- `src-tauri/src/audit_log.rs` 作成 - 監査ログモジュール実装
  - JSON-Lines形式のログ出力（日次ローテーション対応）
  - SHA-256ハッシュチェーン（各レコードにprev_hash + hash、genesisハッシュ起点）
  - 日次ルートハッシュを `root_hashes.jsonl` に別保存
  - ログ保存先: `%APPDATA%/RedactSafe/logs/`（`dirs::data_dir()` 使用）
  - ログファイル名: `audit_YYYY-MM-DD.jsonl`
  - チェーン整合性検証機能（`verify_chain`）
  - OSユーザー名自動取得（`get_current_user`）
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `log_event`: 監査イベント記録（event, user, document_id, data）
  - `get_log_dir`: ログディレクトリパス取得
  - `verify_log_chain`: 指定日のログチェーン検証
  - `AuditState` 状態管理をアプリに統合
- `src-tauri/Cargo.toml` 更新 - 依存関係追加（chrono, sha2, hex, dirs）
- `index.html` 更新 - Audit Logテストパネル追加
- `src/main.js` 更新 - 監査ログテストUIロジック追加

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功
- `cargo clippy` (src-tauri/) - 成功 (warningなし)
- `npm run build` - 成功

**課題:** ブラウザでの動作確認はTauri dev serverの起動権限が未承認のため未実施。ビルド成功で代替確認。

### 2026-04-21 - Task 4: JSONベースの状態管理システムと座標系ユーティリティ

**変更内容:**
- `src-tauri/src/document_state.rs` 作成 - ドキュメント状態管理モジュール実装
  - データ構造定義: `DocumentStatus` (Draft/Confirmed/Finalized), `RegionType` (Name/Address/Phone/Email/BirthDate/MyNumber/CorporateNumber/Custom), `RegionSource` (Auto/Manual), `CoordinateSystem`, `Region`, `PageInfo`, `HistoryEntry`, `MaskingDocument`
  - CRUD操作: 新規作成、JSONファイルからの読込/書込、ページ追加、リージョン追加/切替/削除/BBox更新、一括ON/OFF
  - 状態遷移ロジック: draft→confirmed（確認承認）、confirmed→draft（差し戻し）、confirmed→finalized（確定）、finalizedは不可逆
  - 各遷移でhistoryに自動記録、差し戻し時はrevision自動インクリメント
  - 編集制約: confirmed/finalized状態ではリージョン操作不可
  - 12個のRust単体テスト作成（全テスト通過）
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `create_document`, `get_document`, `get_document_status`, `get_document_summary`
  - `add_page`, `add_region`, `toggle_region`, `remove_region`, `update_region_bbox`, `set_all_regions_enabled`
  - `confirm_document`, `rollback_document`, `finalize_document`
  - `save_document`, `load_document`
  - `DocumentState` 状態管理をアプリに統合
- `python-worker/coord_utils.py` 作成 - 座標変換ユーティリティ
  - `pdf_point_to_pixel` / `pixel_to_pdf_point` - PDF point ↔ pixel 変換
  - `bbox_pdf_point_to_pixel` / `bbox_pixel_to_pdf_point` - bbox変換
  - `rotate_bbox` - ページ回転補正（0°/90°/180°/270°対応）
- `python-worker/worker.py` 更新 - 座標変換JSON-RPCコマンド追加
  - `pdf_point_to_pixel`, `pixel_to_pdf_point`, `bbox_pdf_to_pixel`, `bbox_pixel_to_pdf`, `rotate_bbox`
  - バージョンを0.2.0に更新
- `python-worker/tests/test_coord_utils.py` 作成 - 座標変換単体テスト（20テストケース）
- `index.html` 更新 - Document State Testパネル追加
- `src/main.js` 更新 - ドキュメント状態テストUIロジック追加
- `src/styles.css` 更新 - テスト結果テキストスタイル追加

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ)
- `cargo test` (src-tauri/) - 成功 (12 tests passed)
- `npm run build` - 成功
- `npm run tauri dev` - 成功 (localhost:1420 で起動確認)

**課題:** Pythonがシステムにインストールされていないため、Python単体テストは未実施。Python環境導入後に実行必要。ブラウザ動作確認は権限未承認のためビルド成功で代替。

### 2026-04-21 - Task 5: PDF.jsによるPDFビューアーとマルチページナビゲーション

**変更内容:**
- `src/pdf-viewer.js` 作成 - PDF.jsベースのPDFビューアーモジュール実装
  - `PdfViewer` クラス: PDF読込 (ArrayBuffer/URL対応)、Canvas レンダリング、ページナビゲーション
  - ズーム機能: zoomIn/zoomOut/setZoom (0.25x〜5.0x)、fitToWidth
  - 座標系変換: screenToPdfPoint / pdfPointToScreen / getBBoxInCanvas (PDF point ↔ viewport pixel)
  - ページ情報取得: getPageInfo、非同期レンダリングの重複防止 (pendingPage pattern)
  - コールバック: onPageChange, onZoomChange, onLoad
- `index.html` 更新 - UIレイアウト再構築
  - PDFツールバー追加: [PDFを開く] [ズーム(−/+/幅に合わせ)] [ページ(«/入力/»)] [座標表示]
  - テストパネルをDebug Panelに移動 (Ctrl+Shift+Dでトグル表示、オーバーレイ形式)
  - ドラッグ&ドロップ対応のPDFコンテナ (canvas + placeholder)
  - フッターツールバーのボタンID重複解消 (btn-all-on → btn-toolbar-all-on)
- `src/styles.css` 更新 - PDFビューアーUIスタイル追加
  - PDFツールバー: flexレイアウト、グループ区切り
  - PDFコンテナ: スクロール可能、中央配置、has-pdf時は左上寄せ
  - Canvas: ボックスシャドウ、表示/非表示制御
  - Debugオーバーレイ: セミトランスペアレント背景、モーダル風パネル
  - 座標表示: monospace、右寄せ
- `src/main.js` 更新 - PDFビューアー統合
  - Tauri環境とブラウザ環境の両方で動作するファイルオープン実装
    - Tauri: `@tauri-apps/plugin-dialog` + `convertFileSrc` でファイル読込
    - ブラウザ: HTML file input フォールバック
  - ドラッグ&ドロップによるPDF読込対応
  - キーボードショートカット: Ctrl+O(開く), ←/→(ページ切替), Ctrl+/−(ズーム), Ctrl+0(100%), Ctrl+Shift+D(Debug)
  - マウス移動時のPDF point座標リアルタイム表示
  - ページ入力フィールド (Enterでジャンプ)
- `src-tauri/Cargo.toml` 更新 - `tauri-plugin-dialog = "2"` 追加
- `src-tauri/capabilities/default.json` 更新 - `"dialog:default"` 権限追加
- `src-tauri/src/lib.rs` 更新 - `tauri_plugin_dialog::init()` プラグイン登録
- npm: `pdfjs-dist`, `@tauri-apps/plugin-dialog` 追加

**実行コマンド:**
- `npm install pdfjs-dist @tauri-apps/plugin-dialog` - 成功
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功 (dist/ にビルド出力、pdf.worker.min.mjs 含む)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** ブラウザ動作確認は権限未承認のため未実施。10ページテストPDFでの動作確認は手動テストが必要。

### 2026-04-21 - Task 6: ファイル入力機能（ファイルピッカー・ドラッグ&ドロップ・暗号化PDF・署名付きPDF）

**変更内容:**
- `python-worker/worker.py` 更新 - PDFメタデータ検出メソッド追加
  - `handle_analyze_pdf`: PyMuPDFでPDF解析（暗号化検出、署名検出、ページ情報、SHA-256ハッシュ、メタデータ）
  - `handle_decrypt_pdf`: パスワード付きPDFの復号試行
  - `_open_pdf` ヘルパー: base64デコード→PyMuPDFオープン→パスワード認証
  - バージョンを0.3.0に更新
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `analyze_pdf`: Pythonワーカー経由でPDF解析（base64エンコードされたPDFデータ + パスワード）
  - `decrypt_pdf`: Pythonワーカー経由でPDF復号
  - invoke_handlerに新コマンドを登録
- `index.html` 更新 - モーダルダイアログ追加
  - パスワード入力ダイアログ (`#password-dialog`): 暗号化PDF検出時に表示
  - 署名付きPDF警告ダイアログ (`#signature-dialog`): デジタル署名検出時に表示
- `src/styles.css` 更新 - モーダル・ドロップゾーンスタイル追加
  - `.modal-overlay`: フルスクリーンセミトランスペアレント背景
  - `.modal-content`: 中央配置の白いカード（420px幅）
  - `.modal-btn-primary` / `.modal-btn-secondary`: プライマリ（青）/セカンダリ（白）ボタン
  - `#pdf-container.drag-over`: ドラッグオーバー時の枠線 + ドロップテキストオーバーレイ
- `src/main.js` 更新 - ファイルオープンフロー全面改修
  - `showPasswordDialog()`: Promiseベースのパスワード入力ダイアログ（Enter/Escape対応）
  - `showSignatureDialog()`: Promiseベースの署名警告ダイアログ
  - `arrayBufferToBase64()`: ArrayBuffer → base64エンコードユーティリティ
  - `analyzePdfWithWorker()`: Pythonワーカー経由のPDF解析呼び出し
  - `decryptPdfWithWorker()`: Pythonワーカー経由のPDF復号呼び出し
  - `loadPdfWithAnalysis()`: メインPDF読込フロー
    1. PythonワーカーでPDF解析（暗号化・署名検出）
    2. 暗号化PDFの場合: パスワードダイアログ表示（ループで正しいパスワード入力まで）
    3. 署名付きPDFの場合: 警告ダイアログ表示（続行/キャンセル）
    4. 解析成功時: SHA-256ハッシュでドキュメント状態作成 + ページ情報追加
    5. PDF.jsでPDFビューアーに読み込み
  - `openPdfFile()` / ドラッグ&ドロップ: `loadPdfWithAnalysis()` を使用するよう変更
  - `pdfViewer.onLoad` コールバック: `document_created` イベントを監査ログに記録
  - ドラッグ&ドロップ: CSSクラス (`drag-over`) ベースに変更（インラインスタイルから移行）

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功
- `npm run tauri dev` - アプリ起動成功

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonワーカーが未導入のため、暗号化/署名検出の実行時テストは未実施。Python環境導入後に動作確認が必要。

### 2026-04-21 - Task 7: PaddleOCRによるレイアウト解析・文字認識パイプライン

**変更内容:**
- `python-worker/ocr_pipeline.py` 作成 - OCRパイプラインモジュール実装
  - `analyze_layout()`: PaddleOCR PPStructureによるレイアウト解析（段落・表・図・ヘッダ等の領域分類）
  - `recognize_text_paddleocr()`: PaddleOCR文字認識によるテキスト・bbox抽出（日本語対応、angle_cls有効）
  - `recognize_text_tesseract()`: Tesseract OCRによるフォールバック（pytesseract使用、jpn+eng対応）
  - `run_ocr_pipeline()`: フルOCRパイプライン統合（レイアウト解析→PaddleOCR文字認識→低信頼度(< 0.5)領域にTesseractフォールバック）
  - `_merge_ocr_results()`: PaddleOCRとTesseract結果のIoUベース統合（重複領域の高信頼度結果を採用）
  - `_render_page_to_image()`: PyMuPDFでPDFページを指定DPIで画像化（デフォルト300dpi）
  - `run_ocr_pipeline_base64()`: base64エンコードPDFデータからのパイプライン実行（JSON-RPC用エントリポイント）
  - `run_layout_analysis_base64()`: base64エンコードPDFデータからのレイアウト解析（JSON-RPC用エントリポイント）
  - 遅延初期化パターン: PaddleOCR/PPStructureエンジンの初回使用時に初期化
  - Tesseract可用性チェック: `shutil.which("tesseract")` で実行可能バイナリ確認
- `python-worker/worker.py` 更新
  - `handle_run_ocr`: OCRパイプラインJSON-RPCハンドラ追加（pdf_data, page_num, dpi, password パラメータ）
  - `handle_run_layout_analysis`: レイアウト解析JSON-RPCハンドラ追加
  - バージョンを0.4.0に更新
  - HANDLERSディスパッチテーブルに `run_ocr`, `run_layout_analysis` を追加
- `python-worker/requirements.txt` 更新 - `pytesseract>=0.3.10` 追加
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `run_ocr`: Pythonワーカー経由でOCRパイプライン実行（pdf_data_base64, page_num, dpi, password）
  - `run_layout_analysis`: Pythonワーカー経由でレイアウト解析実行
  - invoke_handlerに新コマンドを登録

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功
- `npm run tauri dev` - アプリ起動成功 (localhost:1420)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** PaddleOCR/Tesseractの実行時テストはPython環境 + モデル導入後に動作確認が必要。テストスキャンPDF（300dpi）でのレイアウト解析・OCR結果確認が保留中。

### 2026-04-21 - Task 8: デジタルネイティブPDFのテキスト抽出経路（PyMuPDF）

**変更内容:**
- `python-worker/ocr_pipeline.py` 更新 - デジタルPDFテキスト抽出機能を実装
  - `check_text_layer()`: PyMuPDFでページのテキストレイヤー有無を判定（`get_text("dict")`でtext block > line > spanを走査）
  - `extract_text_digital()`: `get_text("rawdict")`で文字クワッドから行単位のテキスト・bboxを抽出（PDF point座標、confidence=1.0固定）
  - `extract_text_digital_base64()`: base64エンコードPDFデータからのデジタルテキスト抽出（JSON-RPC用エントリポイント）
  - `run_text_extraction()`: 統合テキスト抽出 - テキストレイヤーが存在する場合はデジタル抽出、存在しない場合はOCRパイプラインにフォールバック
  - 各テキストリージョンにid(UUID)、bbox_pt(PDF point座標)、text、confidence(1.0)、engine("digital_extraction")、font情報、block_bboxを付与
- `python-worker/worker.py` 更新
  - `handle_extract_text_digital`: デジタルテキスト抽出JSON-RPCハンドラ追加
  - `handle_run_text_extraction`: 統合テキスト抽出JSON-RPCハンドラ追加（デジタル→OCR自動フォールバック）
  - HANDLERSディスパッチテーブルに `extract_text_digital`, `run_text_extraction` を追加
  - バージョンを0.5.0に更新
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `extract_text_digital`: Pythonワーカー経由でデジタルテキスト抽出（pdf_data_base64, page_num, password）
  - `run_text_extraction`: Pythonワーカー経由で統合テキスト抽出（pdf_data_base64, page_num, dpi, password）
  - invoke_handlerに新コマンドを登録

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功
- `npm run tauri dev` - アプリ起動成功 (localhost:1420)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonがシステムにインストールされていないため、デジタルPDFのテストファイルでの実行時テストは未実施。Python環境導入後に動作確認が必要。

### 2026-04-21 - Task 9: bbox出力の正規化（座標変換・行統合・回転補正）

**変更内容:**
- `python-worker/coord_utils.py` 更新 - `bbox_pixel_to_pdf_point`のバグ修正（戻り値が3要素 `[x_pt, y_pt, h_pt]` → 4要素 `[x_pt, y_pt, w_pt, h_pt]` に修正）
- `python-worker/bbox_normalizer.py` 作成 - bbox正規化モジュール実装
  - `normalize_bboxes()`: フル正規化パイプライン（ピクセル→PDF point変換 → 行統合 → 回転補正）
  - `_convert_bboxes_to_pdf_points()`: 全リージョンのbbox_pxをbbox_pt（PDF point座標）に変換
  - `_group_and_merge_lines()`: 垂直方向の近接性に基づいてbboxを行グループに分類し、各グループの最小外接矩形に統合
  - `_is_same_line()`: 2つのbboxが同一行かどうかを判定（垂直オーバーラップまたは閾値内の近接性）
  - `_merge_group()`: グループ内のbboxを1つのbboxにマージ（テキスト連結・信頼度平均化）
  - `_apply_rotation()`: 全リージョンにページ回転補正（0°/90°/180°/270°）を適用
  - `normalize_ocr_results()`: JSON-RPC用エントリポイント（base64 PDFデータ → ページ寸法自動取得 → 正規化実行）
  - `line_merge_threshold`: bbox高さの50%を近接閾値として使用（カスタマイズ可能）
- `python-worker/worker.py` 更新
  - `bbox_normalizer`モジュールをインポート
  - `handle_normalize_bboxes`: bbox正規化JSON-RPCハンドラ追加（pdf_data, page_num, regions, dpi, rotation_deg, password, merge_lines パラメータ）
  - HANDLERSディスパッチテーブルに `normalize_bboxes` を追加
  - バージョンを0.6.0に更新
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `normalize_bboxes`: Pythonワーカー経由でbbox正規化実行（pdf_data_base64, page_num, regions, dpi, rotation_deg, password, merge_lines）
  - invoke_handlerに新コマンドを登録
  - `#[allow(clippy::too_many_arguments)]` アノテーション追加
- `python-worker/tests/test_bbox_normalizer.py` 作成 - bbox正規化単体テスト（27テストケース）
  - TestConvertBboxesToPdfPoints: 単一変換、空入力、bboxなし、異なるDPI
  - TestIsSameLine: オーバーラップ、近接、遠隔、包含、異なる高さ
  - TestGroupAndMergeLines: 同一行マージ、異行分離、単一、空入力、3つ同一行、複数行
  - TestApplyRotation: 0°/90°/180°/270°回転、bboxなし
  - TestNormalizeBboxes: フルパイプライン統合（マージあり/なし、回転あり、空入力）
  - TestMergeGroup: 2リージョンマージ、テキスト/信頼度なし

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功 (dist/ にビルド出力)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonがシステムにインストールされていないため、単体テストの実行時確認と回転付きテストPDFでの動作確認は未実施。Python環境導入後に実行必要。

### 2026-04-21 - Task 10: 正規表現によるPII自動検出エンジンを実装

**変更内容:**
- `python-worker/detection_rules.yaml` 作成 - デフォルトPII検出ルールをYAML形式で定義
  - 住所検出: 47都道府県名 + 番地パターン（漢数字対応）
  - 電話番号検出: 市外局番パターン（ハイフンあり/なし、0X-XXX-XXXX等）
  - マイナンバー検出: 12桁数字（lookbehind/lookaheadで前後数字除外）
  - メールアドレス検出: RFC準拠パターン
  - 生年月日検出: 西暦（YYYY年MM月DD日, YYYY/MM/DD, YYYY-MM-DD）+ 和暦（令和/平成/昭和/大正/明治 + 元年対応）
  - 法人番号検出: 13桁数字（lookbehind/lookaheadで前後数字除外）
- `python-worker/pii_detector.py` 作成 - PII検出エンジンモジュール実装
  - `load_rules()`: YAMLファイルから検出ルール読込
  - `load_rules_from_string()`: YAML文字列から検出ルール読込
  - `_compile_rules()`: ルールの正規表現コンパイル（無効パターンのスキップ対応）
  - `detect_pii()`: テキストリージョン群に対するPII検出（bbox, confidence連鎖, type フィルタリング対応）
  - `detect_pii_text()`: 単一テキスト文字列のPII検出（テスト用ユーティリティ）
  - `detect_pii_base64()`: PDFページからのPII検出（テキスト抽出 + 検出の統合エントリポイント）
  - 各検出結果に id(UUID), text, bbox_pt, type, confidence, source, rule_id, rule_name, start, end, original_region_id を付与
- `python-worker/worker.py` 更新
  - `handle_detect_pii`: テキストリージョンに対するPII検出JSON-RPCハンドラ
  - `handle_detect_pii_pdf`: PDFページからのPII検出JSON-RPCハンドラ（テキスト抽出統合）
  - `handle_load_detection_rules`: 検出ルール読込JSON-RPCハンドラ
  - HANDLERSディスパッチテーブルに `detect_pii`, `detect_pii_pdf`, `load_detection_rules` を追加
  - バージョンを0.7.0に更新
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `detect_pii`: Pythonワーカー経由でPII検出（text_regions, enabled_types, rules_path）
  - `detect_pii_pdf`: Pythonワーカー経由でPDFページPII検出（pdf_data_base64, page_num, enabled_types, rules_path, password）
  - `load_detection_rules`: Pythonワーカー経由で検出ルール読込
  - invoke_handlerに新コマンドを登録
- `python-worker/tests/test_pii_detector.py` 作成 - PII検出エンジン単体テスト（53テストケース）
  - TestLoadRules: デフォルトルール読込, 必須フィールド確認, 文字列読込, 空文字列, ルール数確認
  - TestAddressDetection: フルアドレス, 大阪, 北海道, 漢数字, 番地接尾辞, 都道府県のみ不可, 複数住所, 区有り
  - TestPhoneDetection: ハイフンあり, 携帯, ハイフンなし, マイナンバーとの非混同, フリーダイヤル
  - TestMyNumberDetection: 12桁, 11桁不可, 13桁不可(法人番号), 文中埋込, 先頭ゼロ
  - TestEmailDetection: 基本, ドット付, プラス付, サブドメイン, @マーク誤検出なし
  - TestBirthDateDetection: 西暦年月日, スラッシュ区切り, ハイフン区切り, 令和, 平成, 昭和, 元年, 桁数, スペース
  - TestCorporateNumberDetection: 13桁, 12桁不可, 14桁不可, 文中埋込
  - TestDetectPiiWithRegions: bbox保持, region_id保持, confidence連鎖, 空リージョン, テキストなし, 複数検出
  - TestEnabledTypesFilter: 型フィルタリング, 空リスト, None=全件
  - TestDetectionResultStructure: 必須フィールド, source=auto, confidence範囲, UUID形式
  - TestMixedPiiDetection: 個人情報ブロック, 法人文書

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功
- `npm run tauri dev` - アプリ起動成功 (localhost:1420)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonがシステムにインストールされていないため、単体テストの実行時確認は未実施。Python環境導入後に実行必要。

### 2026-04-21 - Task 11: MeCabによる氏名検出とカスタム検出ルールシステムを実装

**変更内容:**
- `python-worker/name_detector.py` 作成 - MeCab形態素解析による氏名検出モジュール実装
  - `detect_names()`: fugashi (MeCab wrapper) + UniDicによる形態素解析で固有名詞（人名）を検出
  - 連続する人名トークンをグルーピングしてフルネームを検出（姓+名のペアで高信頼度）
  - 敬称（様/氏/さん/殿/先生）の後続で信頼度ブースト
  - `_get_pos_fields()`: UniDic品詞情報の抽出（pos1/pos2/pos3/pos4対応）
  - `_is_name_token()`: 人名姓/人名名/人名の判定
  - `_calculate_name_confidence()`: トークン数・姓/名の有無・敬称の有無による信頼度計算
  - 遅延初期化パターン: fugashi未インストール時はgraceful degradation
  - 検出結果に type="name", rule_id="name_mecab", rule_name="氏名（MeCab形態素解析）" を付与
- `python-worker/pii_detector.py` 大幅拡張
  - `check_regex_safety()`: ReDoS（catastrophic backtracking）検出を実装
    - ネストされた量子子の検出: `(a+)+`, `(a*)*`, `(a+)*`
    - 量子子付き選択の検出: `(a|a)+`
    - 大きな繰り返し範囲の検出: `{0,200}`
    - 複雑なグループへの非制限量子子の検出
  - `validate_rule()`: 単一ルールのスキーマ検証を実装
    - 必須フィールド検証: id, name, type, pattern
    - 型検証: type は VALID_PII_TYPES に含まれること
    - 正規表現の妥当性・安全性チェック
    - confidence の範囲チェック (0.0-1.0)
    - enabled の型チェック (boolean)
    - 未知フィールドの検出
  - `validate_rules()`: ルールリストの検証 + 重複ID検出
  - `load_rules_from_string()`: YAML/JSON文字列からのルール読込（フォーマット自動検出対応）
  - `load_custom_rules()`: custom_rules/ ディレクトリからのカスタムルール読込
    - YAML/JSON ファイルの自動発見と読込
    - スキーマ検証不合格ルールのスキップ
    - ID競合の検出
  - `merge_rules()`: 本体同梱ルールとカスタムルールのマージ（カスタムで同ID上書き）
  - `_get_custom_rules_dir()`: カスタムルールディレクトリパス取得
  - `detect_pii()` 拡張: MeCab名前検出の統合、カスタムルール読込、正規表現タイムアウト保護
  - `detect_pii_base64()` / `detect_pii_text()` に enable_name_detection, custom_rules_dir パラメータ追加
  - `VALID_PII_TYPES`, `REGEX_TIMEOUT_SECONDS`, `REGEX_MAX_STEPS` 定数定義
- `python-worker/custom_rules/` ディレクトリ作成
  - `example_custom_rules.yaml`: カスタムルールのサンプル（コメントアウト例付き）
  - `README.md`: カスタムルールのドキュメント
- `python-worker/worker.py` 更新
  - インポート追加: `load_custom_rules`, `merge_rules`, `validate_rules`, `check_regex_safety`, `load_rules_from_string`
  - `handle_load_custom_rules`: カスタムルール読込JSON-RPCハンドラ追加
  - `handle_load_all_rules`: 本体+カスタム統合読込JSON-RPCハンドラ追加
  - `handle_validate_rules`: ルールスキーマ検証JSON-RPCハンドラ追加
  - `handle_check_regex_safety`: 正規表現安全性チェックJSON-RPCハンドラ追加
  - `handle_detect_names`: MeCab氏名検出JSON-RPCハンドラ追加
  - `handle_detect_pii` / `handle_detect_pii_pdf`: enable_name_detection, custom_rules_dir パラメータ対応
  - HANDLERSに5つの新メソッド追加
  - バージョンを0.8.0に更新
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `detect_pii`: enable_name_detection, custom_rules_dir パラメータ追加
  - `detect_pii_pdf`: enable_name_detection, custom_rules_dir パラメータ追加
  - `load_custom_rules`: カスタムルール読込コマンド追加
  - `load_all_rules`: 統合ルール読込コマンド追加
  - `validate_rules`: ルール検証コマンド追加
  - `check_regex_safety`: 正規表現安全性チェックコマンド追加
  - `detect_names`: MeCab氏名検出コマンド追加
  - invoke_handlerに5つの新コマンド登録（合計37コマンド）
- `python-worker/tests/test_name_detector.py` 作成 - 氏名検出単体テスト（18テストケース）
  - TestIsNameToken: 人名/姓/名/非人名/動詞/地名の判定
  - TestCalculateNameConfidence: 単一/フルネーム/敬称ブースト/空/上限
  - TestDetectNames: 基本検出/敬称/空テキスト/非固有名詞/bbox保持/型フィルタ/結果構造
- `python-worker/tests/test_custom_rules.py` 作成 - カスタムルール・検証・安全性テスト（52テストケース）
  - TestRegexSafety: 安全パターン/ネスト量子子/選択/大繰り返し/複雑グループ/既存パターン安全性
  - TestValidateRule: 有効/必須フィールド欠落/無効型/無効パターン/安全でないパターン/信頼度範囲外/有効型全種別
  - TestValidateRules: 有効リスト/重複ID/混在/空リスト
  - TestLoadRulesFromString: YAML/JSON/自動検出/空文字/無効コンテンツ
  - TestMergeRules: 非上書き/上書き/空カスタム/空本体
  - TestLoadCustomRules: 非存在/空/YAML/JSON/無効スキップ/非ルールファイル/複数ファイル

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonがシステムにインストールされていないため、MeCab単体テストの実行時確認は未実施。Python環境導入後にfugashi/unidic-liteでの動作確認が必要。

### 2026-04-21 - Task 12: OCR・検出処理のプログレス表示を実装する

**変更内容:**
- `python-worker/worker.py` 更新
  - `send_progress()` 関数を追加 - stderr経由でJSON形式の進捗通知を送信
  - `process_message()` を更新 - `inspect.signature` でハンドラが `request_id` パラメータを受け取るかチェックし、対応するハンドラに渡す
  - `handle_run_ocr`, `handle_run_text_extraction`, `handle_detect_pii_pdf` に `request_id` パラメータと `progress_callback` を追加
- `python-worker/ocr_pipeline.py` 更新
  - `run_ocr_pipeline()` に `progress_callback` パラメータを追加 - レイアウト解析/文字認識/Tesseractチェックの各ステップで進捗通知
  - `run_ocr_pipeline_base64()` に `progress_callback` パラメータを追加
  - `run_text_extraction()` に `progress_callback` パラメータを追加 - テキストレイヤー確認/デジタル抽出/OCRフォールバックの各ステップで進捗通知
- `python-worker/pii_detector.py` 更新
  - `detect_pii_base64()` に `progress_callback` パラメータを追加 - テキスト抽出/PII検出の各ステップで進捗通知
- `src-tauri/src/python_worker.rs` 大幅更新
  - `ProgressEvent` 構造体を定義 - stderrのJSON進捗通知をデシリアライズ
  - `PythonWorker` に `_stderr_thread` と `stderr_stop` フィールドを追加
  - `spawn_stderr_reader()` メソッドを追加 - stderrを非同期で読み取り、進捗通知をTauriイベント (`worker-progress`) としてフロントエンドに転送
  - `spawn()` メソッドを更新 - 子プロセスのstderrを `take()` で取得し、読み取りスレッドを起動
  - `kill()` メソッドを更新 - `stderr_stop` フラグで読み取りスレッドを終了
- `src-tauri/src/lib.rs` 更新
  - `cancel_worker` Tauriコマンドを追加 - ワーカープロセスを終了し、`worker-cancelled` イベントをフロントエンドに送信
  - `invoke_handler` に `cancel_worker` を登録（合計38コマンド）
  - `tauri::Emitter` trait をインポート
- `index.html` 更新
  - `<footer>` 内に `#progress-container` を追加
    - `#progress-bar-track` / `#progress-bar-fill`: プログレスバー
    - `#progress-info`: メッセージ + パーセント表示 + キャンセルボタン
    - `#progress-stale-warning`: 処理停止警告バナー
- `src/styles.css` 更新
  - プログレスバー関連スタイル追加（トラック・フィル・インジケータ・アニメーション）
  - indeterminateアニメーション（総ステップ数不明時のスライドアニメーション）
  - キャンセルボタンスタイル（赤枠・ホバー時背景赤）
  - 処理停止警告バナースタイル
  - footer を flex-direction: column に変更しツールバーとプログレスバーを縦に配置
- `src/main.js` 更新
  - `progressManager` オブジェクトを実装
    - `show()`: プログレスバー表示・Tauriイベントリスナー登録・stale検出タイマー開始
    - `update(payload)`: 進捗バー更新（メッセージ・パーセント・インジケータ幅）
    - `hide()`: プログレスバー非表示・タイマー停止
    - `_checkStale()`: 2秒ごとに最終更新からの経過時間をチェック、10秒超過で警告表示
  - `invokeWithProgress()` ヘルパー関数を追加 - 任意のワーカーコマンドをプログレス追跡付きで実行
  - `analyzePdfWithWorker()` を更新 - プログレス表示付きでPDF解析を実行
  - キャンセルボタンのクリックハンドラーを実装

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonワーカーが未導入のため、実行時のプログレス通知の動作確認は未実施。Python環境導入後にOCR/PII検出のプログレス表示を確認必要。

### 2026-04-21 - Task 13: 仮マスキングオーバーレイエンジン（Canvas API）を実装する

**変更内容:**
- `src/masking-overlay.js` 作成 - Canvas APIベースのマスキングオーバーレイエンジン実装
  - `MaskingOverlay` クラス: PDFビューア上にオーバーレイレイヤーを重ねてマスキング矩形を描画
  - `setRegions()`: リージョン配列を設定して描画
  - `setSelectedRegion()`: 選択状態を設定（赤枠 + コーナーハンドル表示）
  - `setHoveredRegion()`: ホバー状態を設定（枠色を薄く変更）
  - `resize()`: PDF canvas寸法に合わせてオーバーレイcanvasをリサイズ
  - `clear()`: 全リージョンと選択状態をクリア
  - `findRegionAtPoint()`: マウス座標からリージョンを検出（逆順で最上位優先）
  - `_drawRegion()`: 各リージョンの描画
    - 有効時: 黒矩形(#000000)塗りつぶし
    - 無効時: 半透明グレー(#808080, 50%)
    - 選択時: 赤枠(#FF0000, 2.5px) + 4コーナーハンドル(6px) + 4辺中点ハンドル
    - 自動検出: 青枠(#4488FF)、ホバー時(#6699FF)
    - 手動追加: 緑枠(#44AA44)、ホバー時(#66CC66)
- `index.html` 更新 - オーバーレイテストパネルをDebug Panelに追加
  - [Add Test Regions] [Add Manual Region] [Clear Overlay]
  - [Toggle ON] [Toggle OFF] [Select Next] [Deselect]
- `src/main.js` 更新
  - `MaskingOverlay` インポート・初期化
  - `pdfViewer.onPageChange` でオーバーレイリサイズ + リージョン取得
  - `fetchAndDisplayRegions()`: バックエンドからページリージョンを取得してオーバーレイに設定
  - `overlayCanvas` でのmousemoveイベント: 座標表示 + ホバーハイライト
  - `overlayCanvas` でのclickイベント: リージョン選択
  - デバッグパネルのテストボタン群のイベントハンドラー実装

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)
- `npm run build` - 成功

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** 実際のPDFでのオーバーレイ描画確認はブラウザ/アプリ起動権限が必要。コードレビューにより座標同期・描画ロジックの妥当性を確認済み。

### 2026-04-21 - Task 14: マスキング矩形の操作（ON/OFF・移動・リサイズ・追加・削除）を実装

**変更内容:**
- `src/undo-manager.js` 作成 - UndoManagerクラス実装
  - 操作のundoスタック（最大50深度）を管理
  - 操作タイプ: add, remove, move, resize, toggle
  - 各操作にpageNum, regionId, snapshot/prevBboxを記録
- `src/masking-overlay.js` 更新 - ハンドル検出機能を追加
  - `findHandleAtPoint()`: 選択中リージョンの8つのリサイズハンドル（四隅+辺中点）のヒットテスト
  - `cursorForHandle()`: ハンドルIDに対応するカーソルスタイルを返すstaticメソッド
  - `HANDLE_SIZE` static定数（6px）
- `src/main.js` 大幅更新 - 対話エンジン実装
  - `InteractionMode`: NONE / MOVE / RESIZE / DRAW_NEW の4つの対話モード
  - `onOverlayMouseDown()`: ハンドル→リサイズ、リージョン→移動、空白→新規描画を判定
  - `onOverlayMouseMove()`: ドラッグ中のリアルタイム座標更新（PDF point座標系で計算）
    - 移動: startBboxからのdelta適用
    - リサイズ: 8方向ハンドルに応じたbbox再計算（最小サイズ5pt制限）
    - 新規描画: ダッシュ線プレビュー矩形を描画
  - `onOverlayMouseUp()`: 操作確定時にundoスタックpush + バックエンドpersist + 監査ログ + 自動保存
  - `performUndo()`: Ctrl+Zによる操作取り消し（move/resizeはbbox復元、addは削除、removeは再追加、toggleは再切替）
  - `deleteSelectedRegion()`: Delete/Backspaceキーで選択中リージョンを削除
  - `toggleSelectedRegion()`: SpaceキーまたはダブルクリックでON/OFF切替
  - `persistRegionUpdate()`, `persistAddRegion()`, `persistRemoveRegion()`, `persistToggleRegion()`: Tauri/ブラウザ両モード対応のバックエンド書込
  - `logAuditEvent()`: 各操作の監査ログ記録（region_moved, region_resized, region_added, region_deleted, region_toggled, undo_*）
  - `autoSaveDocument()`: 各操作後にJSON自動保存
  - マウスカーソル: 空白時crosshair、リージョン上move、ハンドル上resize
  - キーボードショートカット追加: Ctrl+Z(Undo), Delete(削除), Space(ON/OFF切替)
  - デバッグパネルのAll ON/OFFボタンに監査ログ記録・自動保存を追加

**実行コマンド:**
- `npm run build` - 成功 (dist/ にビルド出力)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ、既存分)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** ブラウザでの対話操作テスト（ドラッグ・リサイズ・新規描画）は権限未承認のため未実施。コードレビューにより座標計算・イベントハンドリングの妥当性を確認済み。
