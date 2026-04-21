# RedactSafe - Activity Log

## Current Status
**Last Updated:** 2026-04-21
**Tasks Completed:** 9 / 25
**Current Task:** Task 9 - bbox出力の正規化（座標変換・行統合・回転補正） (完了)

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
