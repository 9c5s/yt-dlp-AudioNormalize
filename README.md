# yt-dlp-audio-normalize

[ffmpeg-normalize](https://github.com/slhck/ffmpeg-normalize) を使用した音声正規化のための yt-dlp PostProcessor プラグイン

## 要件

- Python >= 3.10
- yt-dlp >= 2026.2.4
- ffmpeg (システムにインストール済みであること)

## インストール

```bash
pip install -U yt-dlp-audio-normalize
```

## 使い方

### --use-postprocessor

```bash
# デフォルトの正規化
yt-dlp --use-postprocessor AudioNormalize URL

# パラメータを指定
yt-dlp --use-postprocessor "AudioNormalize:target_level=-14.0;audio_codec=aac" URL

# 実行タイミングを指定
yt-dlp --use-postprocessor "AudioNormalize:when=after_move" URL
```

### --ppa (PostProcessor Arguments)

```bash
yt-dlp --ppa "AudioNormalize:-t -14.0 -c:a aac -b:a 128k" URL
```

`--use-postprocessor` の kwargs と `--ppa` の両方が指定された場合、PPA が優先される。

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
|------|-----------|------|
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
