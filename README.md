# yt-dlp-audio-normalize

[![CI](https://github.com/9c5s/yt-dlp-AudioNormalize/actions/workflows/ci.yml/badge.svg)](https://github.com/9c5s/yt-dlp-AudioNormalize/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/yt-dlp-audio-normalize)](https://pypi.org/project/yt-dlp-audio-normalize/)
[![Python](https://img.shields.io/pypi/pyversions/yt-dlp-audio-normalize)](https://pypi.org/project/yt-dlp-audio-normalize/)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

[ffmpeg-normalize](https://github.com/slhck/ffmpeg-normalize) を使用した音量正規化のための yt-dlp PostProcessor プラグイン

## 要件

- Python >= 3.10
- yt-dlp
- ffmpeg (システムにインストール済みであること)

## インストール

```bash
pip install -U yt-dlp-audio-normalize
```

## 使用方法

### --use-postprocessor

```bash
# デフォルト
yt-dlp --use-postprocessor AudioNormalize URL

# パラメータを指定
yt-dlp --use-postprocessor "AudioNormalize:target_level=-14.0;audio_codec=aac" URL

# 実行タイミングを指定
yt-dlp --use-postprocessor "AudioNormalize:when=pre_process" URL
```

`when` を省略した場合、自動的に `after_move` で実行される。これにより、ファイルが最終パスに移動された後に音量正規化が行われる。

### --ppa (PostProcessor Arguments)

```bash
yt-dlp --ppa "AudioNormalize:-t -14.0 -c:a aac -b:a 128k" URL
```

`--use-postprocessor` の kwargs と `--ppa` の両方が指定された場合、PPA が優先される。

### 自動推定

ダウンロード済みファイルのメタデータから以下のパラメータが自動的に設定される:

| パラメータ | ソース | 説明 |
| ---------- | ------ | ---- |
| `extension` | `ext` | 出力ファイルの拡張子 |
| `audio_codec` | `acodec` | 音声コーデック(デコーダ名→エンコーダ名に自動変換) |
| `sample_rate` | `asr` | サンプルレート(未取得時は 48000 Hz) |
| `audio_bitrate` | `abr` | 音声ビットレート |

ユーザーが明示的に指定した値は自動推定値より優先される。

### Python API

```python
import yt_dlp
from yt_dlp_plugins.postprocessor.audio_normalize import AudioNormalizePP

with yt_dlp.YoutubeDL(opts) as ydl:
    ydl.add_post_processor(AudioNormalizePP(), when="after_move")
    ydl.download([url])
```

## サポートされるパラメータ

`FFmpegNormalize.__init__()` のすべてのスカラーパラメータは、ロングフラグ(例: `--target-level`, `--audio-codec`)で自動的にサポートされる

### ショートフラグ

| フラグ | パラメータ | 説明 |
| ------ | ----------- | ------ |
| `-nt` | `normalization_type` | 正規化タイプ |
| `-t` | `target_level` | ターゲットレベル |
| `-p` | `print_stats` | 統計情報の表示 |
| `-lrt` | `loudness_range_target` | ラウドネス範囲ターゲット |
| `-tp` | `true_peak` | トゥルーピーク |
| `-c:a` | `audio_codec` | 音声コーデック |
| `-b:a` | `audio_bitrate` | 音声ビットレート |
| `-ar` | `sample_rate` | サンプルレート |
| `-ac` | `audio_channels` | 音声チャンネル数 |
| `-koa` | `keep_original_audio` | 元の音声を保持 |
| `-prf` | `pre_filter` | プリフィルター |
| `-pof` | `post_filter` | ポストフィルター |
| `-vn` | `video_disable` | 映像を無効化 |
| `-c:v` | `video_codec` | 映像コーデック |
| `-sn` | `subtitle_disable` | 字幕を無効化 |
| `-mn` | `metadata_disable` | メタデータを無効化 |
| `-cn` | `chapters_disable` | チャプターを無効化 |
| `-ofmt` | `output_format` | 出力フォーマット |
| `-ext` | `extension` | 拡張子 |
| `-d` | `debug` | デバッグモード |
| `-n` | `dry_run` | ドライラン |
| `-pr` | `progress` | 進捗表示 |

## ライセンス

[Unlicense](LICENSE)
