"""ffmpeg-normalizeで音量を正規化するyt-dlp PostProcessorプラグイン

使用方法:
    --use-postprocessor "AudioNormalize:target_level=-14.0;audio_codec=aac"
    --ppa "AudioNormalize:-t -14.0 -c:a aac"
"""

from __future__ import annotations

import functools
import os
import shutil
import tempfile
import types
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from ffmpeg_normalize import FFmpegNormalize, FFmpegNormalizeError
from yt_dlp.postprocessor.common import PostProcessor

if TYPE_CHECKING:
    from yt_dlp.extractor.common import _InfoDict  # pyright: ignore[reportPrivateUsage]


class AudioNormalizePP(PostProcessor):
    """ffmpeg-normalizeで音量を正規化するyt-dlp PostProcessorプラグイン

    --ppa "AudioNormalize:ARGS" でffmpeg-normalizeのパラメータを上書きできる
    --use-postprocessor "AudioNormalize:key=value" でもパラメータを指定できる
    FFmpegNormalize.__init__の全スカラーパラメータを長形式フラグで自動サポートし、
    短縮フラグも提供する
    bool型パラメータは値なしフラグとして指定可能(例: --dual-mono)
    PPA引数が指定された場合、--use-postprocessor経由のkwargsより優先される
    """

    # 短縮フラグ→パラメータ名のマッピング(自動導出不可能なもののみ)
    # https://slhck.info/ffmpeg-normalize/usage/cli-options/
    _SHORT_FLAGS: ClassVar[dict[str, str]] = {
        # 正規化
        "-nt": "normalization_type",
        "-t": "target_level",
        "-p": "print_stats",
        # EBU R128
        "-lrt": "loudness_range_target",
        "-tp": "true_peak",
        # 音声エンコード
        "-c:a": "audio_codec",
        "-b:a": "audio_bitrate",
        "-ar": "sample_rate",
        "-ac": "audio_channels",
        "-koa": "keep_original_audio",
        # フィルタ
        "-prf": "pre_filter",
        "-pof": "post_filter",
        # 映像/字幕/メタデータ
        "-vn": "video_disable",
        "-c:v": "video_codec",
        "-sn": "subtitle_disable",
        "-mn": "metadata_disable",
        "-cn": "chapters_disable",
        # 出力形式
        "-ofmt": "output_format",
        "-ext": "extension",
        # 実行制御
        "-d": "debug",
        "-n": "dry_run",
        "-pr": "progress",
    }

    # アノテーションと実際の使用法が乖離しているパラメータの型オーバーライド
    _TYPE_OVERRIDES: ClassVar[dict[str, type]] = {
        "audio_bitrate": str,  # 型注釈はfloatだが実際はstr("192k"等)を受け付ける
    }

    def __init__(self, downloader: Any = None, **kwargs: str) -> None:  # noqa: ANN401
        """AudioNormalizePPを初期化する

        Args:
            downloader: yt-dlpのダウンローダーインスタンス
            **kwargs: --use-postprocessor経由のパラメータ(全て文字列)
        """
        super().__init__(downloader)
        self._kwargs = kwargs

    @staticmethod
    def _extract_scalar_type(hint: object) -> type | None:
        """型ヒントからスカラー型を抽出する list型の場合はNoneを返す"""
        if isinstance(hint, type) and hint in (str, float, int, bool):
            return hint
        origin = get_origin(hint)
        if origin is Literal:
            first = get_args(hint)[0]
            return type(first) if isinstance(first, (str, int, float, bool)) else str
        if origin is list:
            return None
        if origin is types.UnionType:
            for arg in get_args(hint):
                if arg is not type(None):
                    return AudioNormalizePP._extract_scalar_type(arg)
        return str

    @staticmethod
    @functools.cache
    def _build_param_map() -> dict[str, tuple[str, type]]:
        """PPA引数フラグから(パラメータ名, 型)へのマッピングを自動構築する

        __init__の型アノテーションから長形式フラグと型を自動生成し、
        短縮フラグと型オーバーライドをマージする
        """
        hints = get_type_hints(FFmpegNormalize.__init__)
        param_map: dict[str, tuple[str, type]] = {}
        for param_name, hint in hints.items():
            if param_name == "return":
                continue
            scalar_type = AudioNormalizePP._extract_scalar_type(hint)
            if scalar_type is None:
                continue
            actual_type = AudioNormalizePP._TYPE_OVERRIDES.get(param_name, scalar_type)
            long_flag = "--" + param_name.replace("_", "-")
            param_map[long_flag] = (param_name, actual_type)
        for flag, param_name in AudioNormalizePP._SHORT_FLAGS.items():
            long_flag = "--" + param_name.replace("_", "-")
            if long_flag in param_map:
                param_map[flag] = param_map[long_flag]
        return param_map

    def run(self, information: _InfoDict) -> tuple[list[str], _InfoDict]:
        """ダウンロード済みファイルの音量を正規化する"""
        filepath = information.get("filepath")
        if filepath:
            self._normalize_file(filepath)
        return [], information

    def _build_normalize_kwargs(self) -> dict[str, Any]:
        """PPAの引数とCLI kwargsをFFmpegNormalizeのコンストラクタ引数に変換する

        --use-postprocessor経由のkwargsを基本値とし、
        PPA引数が存在する場合はそちらで上書きする(PPA優先)
        """
        kwargs = self._kwargs_from_cli()
        kwargs.update(self._kwargs_from_ppa())
        return kwargs

    def _kwargs_from_cli(self) -> dict[str, Any]:
        """--use-postprocessor経由のkwargsを型変換して返す

        kwargsのキーはパラメータ名(target_level)だけでなく、
        短縮フラグ(-t)や長形式フラグ(--target-level)も受け付ける
        """
        if not self._kwargs:
            return {}
        kwargs: dict[str, Any] = {}
        param_map = self._build_param_map()
        # パラメータ名→型の逆引きマップを構築する
        type_map: dict[str, type] = {}
        for name, typ in param_map.values():
            type_map.setdefault(name, typ)
        for key, str_val in self._kwargs.items():
            # フラグ形式(-t, -c:a, --target-level等)の解決を試みる
            mapping = param_map.get(key)
            if mapping:
                param_name, typ = mapping
            else:
                typ = type_map.get(key)
                if typ is None:
                    continue
                param_name = key
            if typ is bool:
                kwargs[param_name] = str_val.lower() in ("true", "1", "yes")
            else:
                try:
                    kwargs[param_name] = typ(str_val)
                except (ValueError, TypeError):
                    msg = f"無効なkwargs値: {key}={str_val}"
                    self.report_warning(msg)
        return kwargs

    def _kwargs_from_ppa(self) -> dict[str, Any]:
        """PPA引数をパースしてFFmpegNormalizeのコンストラクタ引数に変換する"""
        kwargs: dict[str, Any] = {}
        args = cast(
            "list[str]",
            self._configuration_args(self.pp_key()),  # type: ignore[attr-defined]
        )
        param_map = self._build_param_map()
        args_iter = iter(args)
        for key in args_iter:
            mapping = param_map.get(key)
            if not mapping:
                # 未知のフラグはスキップする
                # 値付きフラグの場合その値も次のイテレーションでキーとして処理されるが、
                # param_mapのキーは全て"-"で始まるため通常の値は再びここでスキップされる
                continue
            param_name, param_type = mapping
            if param_type is bool:
                kwargs[param_name] = True
            else:
                try:
                    value = next(args_iter)
                    try:
                        kwargs[param_name] = param_type(value)
                    except (ValueError, TypeError):
                        msg = f"無効な引数値: {key} {value}"
                        self.report_warning(msg)
                except StopIteration:
                    msg = f"値が必要な引数の値がありません: {key}"
                    self.report_warning(msg)
        return kwargs

    def _normalize_file(self, filepath: str) -> None:
        """指定されたファイルの音量を正規化する

        一時ファイルに正規化した結果を出力し、成功した場合のみ元ファイルを置換する
        """
        path = Path(filepath)
        if not path.exists():
            msg = f"ファイルが存在しません: {filepath}"
            self.report_warning(msg)
            return

        msg = f"音量の正規化を開始: {path.name}"
        self.to_screen(msg)  # pyright: ignore[reportCallIssue]

        try:
            fd, tmp_path = tempfile.mkstemp(suffix=path.suffix, dir=path.parent)
            os.close(fd)
        except OSError:
            self.report_warning("一時ファイルの作成に失敗しました")
            return

        try:
            norm_kwargs = self._build_normalize_kwargs()
            norm = FFmpegNormalize(**norm_kwargs)
            norm.add_media_file(str(path), tmp_path)
            norm.run_normalization()
            shutil.move(tmp_path, str(path))
            msg = f"音量の正規化が完了: {path.name}"
            self.to_screen(msg)  # pyright: ignore[reportCallIssue]
        except (FFmpegNormalizeError, OSError) as e:
            self.report_warning(f"音量の正規化に失敗しました: {e}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
