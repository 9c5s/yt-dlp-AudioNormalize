from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Union
from unittest.mock import MagicMock, patch

import pytest
from ffmpeg_normalize import FFmpegNormalizeError
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor import plugin_pps
from yt_dlp.postprocessor.common import PostProcessor

import yt_dlp_plugins.postprocessor.audio_normalize
from yt_dlp_plugins.postprocessor.audio_normalize import AudioNormalizePP

if TYPE_CHECKING:
    from pathlib import Path


# === _extract_scalar_type ===


class TestExtractScalarType:
    """型ヒントからスカラー型を抽出すること

    FFmpegNormalize.__init__のパラメータ型アノテーションを解析し、
    CLI引数の文字列を正しい型に変換するための基盤となること
    """

    # --- プレーンなスカラー型 ---

    @pytest.mark.parametrize("hint", [str, int, float, bool])
    def test_scalar_type_returned_as_is(self, hint: type) -> None:
        """str, int, float, boolがそのまま返されること"""
        assert AudioNormalizePP._extract_scalar_type(hint) is hint

    def test_non_scalar_class_falls_back_to_str(self) -> None:
        """未知のユーザー定義クラスがstrにフォールバックされること"""

        class Custom:
            pass

        assert AudioNormalizePP._extract_scalar_type(Custom) is str

    def test_builtin_non_scalar_type_falls_back_to_str(self) -> None:
        """スカラーではない組み込み型(list等)がstrにフォールバックされること"""
        assert AudioNormalizePP._extract_scalar_type(list) is str

    def test_none_type_falls_back_to_str(self) -> None:
        """NoneTypeがstrにフォールバックされること"""
        assert AudioNormalizePP._extract_scalar_type(type(None)) is str

    # --- Literal型 ---

    def test_literal_str_returns_str(self) -> None:
        """Literal["ebu"]の最初の値から型strが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal["ebu"]) is str

    def test_literal_int_returns_int(self) -> None:
        """Literal[1]の最初の値から型intが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal[1]) is int

    def test_literal_negative_int_returns_int(self) -> None:
        """Literal[-1]の負の整数でもintが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal[-1]) is int

    def test_literal_float_returns_float(self) -> None:
        """Literal[1.0]の最初の値から型floatが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal[1.0]) is float

    def test_literal_bool_returns_bool(self) -> None:
        """Literal[True]の最初の値から型boolが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal[True]) is bool

    def test_literal_false_returns_bool(self) -> None:
        """Literal[False]でもboolが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal[False]) is bool

    def test_literal_multiple_str_returns_str(self) -> None:
        """複数の文字列リテラルでも最初の値からstrが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal["a", "b", "c"]) is str

    def test_literal_multiple_int_returns_int(self) -> None:
        """複数の整数リテラルでも最初の値からintが推定されること"""
        assert AudioNormalizePP._extract_scalar_type(Literal[1, 2, 3]) is int

    def test_literal_none_falls_back_to_str(self) -> None:
        """Literal[None]はスカラー値でないためstrにフォールバックされること"""
        assert AudioNormalizePP._extract_scalar_type(Literal[None]) is str  # noqa: PYI061

    # --- list型 ---

    def test_list_type_returns_none(self) -> None:
        """list[str]はスカラーではないためNoneが返されること"""
        assert AudioNormalizePP._extract_scalar_type(list[str]) is None

    def test_list_int_returns_none(self) -> None:
        """list[int]もスカラーではないためNoneが返されること"""
        assert AudioNormalizePP._extract_scalar_type(list[int]) is None

    # --- Union型 ---

    def test_union_with_none_extracts_non_none_type(self) -> None:
        """float | NoneからNoneが除外されてfloatが抽出されること"""
        assert AudioNormalizePP._extract_scalar_type(float | None) is float

    def test_union_str_none_extracts_str(self) -> None:
        """str | NoneからNoneが除外されてstrが抽出されること"""
        assert AudioNormalizePP._extract_scalar_type(str | None) is str

    def test_union_bool_none_extracts_bool(self) -> None:
        """bool | NoneからNoneが除外されてboolが抽出されること"""
        assert AudioNormalizePP._extract_scalar_type(bool | None) is bool

    def test_typing_union_float_none_extracts_float(self) -> None:
        """typing.Union[float, None]からNoneが除外されてfloatが抽出されること"""
        assert AudioNormalizePP._extract_scalar_type(Union[float, None]) is float  # noqa: UP007

    def test_typing_optional_str_extracts_str(self) -> None:
        """typing.Optional[str]からNoneが除外されてstrが抽出されること"""
        assert AudioNormalizePP._extract_scalar_type(Union[str, None]) is str  # noqa: UP007

    # --- フォールバック ---

    def test_unrecognized_generic_type_falls_back_to_str(self) -> None:
        """dict[str, int]等の未対応ジェネリック型がstrにフォールバックされること"""
        assert AudioNormalizePP._extract_scalar_type(dict[str, int]) is str

    def test_string_object_falls_back_to_str(self) -> None:
        """型ではない文字列オブジェクトが渡されてもstrにフォールバックされること"""
        assert AudioNormalizePP._extract_scalar_type("not a type") is str  # type: ignore[arg-type]

    def test_int_object_falls_back_to_str(self) -> None:
        """型ではない整数オブジェクトが渡されてもstrにフォールバックされること"""
        assert AudioNormalizePP._extract_scalar_type(42) is str  # type: ignore[arg-type]


# === _build_param_map ===


class TestBuildParamMap:
    """CLIフラグからパラメータ名と型へのマッピングを自動構築すること

    FFmpegNormalize.__init__の型アノテーションから長形式フラグを自動生成し、
    _SHORT_FLAGSの短縮フラグと_TYPE_OVERRIDESの型補正をマージすること
    """

    def test_returns_dict(self) -> None:
        """戻り値が辞書であること"""
        result = AudioNormalizePP._build_param_map()

        assert isinstance(result, dict)

    def test_long_flags_have_dashes(self) -> None:
        """長形式フラグが"--"で始まること"""
        result = AudioNormalizePP._build_param_map()

        long_flags = [k for k in result if k.startswith("--")]
        assert len(long_flags) > 0

    def test_short_flags_all_included(self) -> None:
        """_SHORT_FLAGSで定義された短縮フラグが全てマッピングに含まれること"""
        result = AudioNormalizePP._build_param_map()

        short_flag_set = set(AudioNormalizePP._SHORT_FLAGS.keys())
        assert short_flag_set <= set(result.keys())

    def test_long_flag_maps_to_param_name(self) -> None:
        """--target-levelがパラメータ名target_levelにマッピングされること"""
        result = AudioNormalizePP._build_param_map()

        assert result["--target-level"][0] == "target_level"

    def test_list_params_excluded(self) -> None:
        """list型パラメータがマッピングから除外されること"""
        result = AudioNormalizePP._build_param_map()

        param_names = {name for name, _ in result.values()}
        assert "extra_input_options" not in param_names

    def test_dual_mono_flag_has_bool_type(self) -> None:
        """--dual-monoの型がboolであること"""
        result = AudioNormalizePP._build_param_map()

        assert result["--dual-mono"][1] is bool

    def test_audio_bitrate_overridden_to_str(self) -> None:
        """audio_bitrateの型が"128k"等を受け付けるためstrに上書きされること"""
        result = AudioNormalizePP._build_param_map()

        assert result["--audio-bitrate"][1] is str
        assert result["-b:a"][1] is str

    def test_return_key_excluded(self) -> None:
        """get_type_hintsの'return'キーがマッピングに含まれないこと"""
        result = AudioNormalizePP._build_param_map()

        assert "--return" not in result

    def test_cache_returns_same_object(self) -> None:
        """functools.cacheにより2回呼んでも同一オブジェクトが返されること"""
        result1 = AudioNormalizePP._build_param_map()
        result2 = AudioNormalizePP._build_param_map()

        assert result1 is result2


# === _build_normalize_kwargs ===


class TestBuildNormalizeKwargs:
    """PPA引数(--ppa "AudioNormalize:...")をパースすること

    yt-dlpの--ppaオプション経由で渡されたCLI引数文字列を解析し、
    FFmpegNormalizeコンストラクタに渡すkwargsに変換すること
    """

    def test_empty_ppa_returns_empty_dict(self, make_pp) -> None:
        """PPA引数なしなら空の辞書が返されること"""
        pp = make_pp([])

        result = pp._build_normalize_kwargs()

        assert result == {}

    def test_long_flag_with_value(self, make_pp) -> None:
        """長形式フラグ--target-level -14.0がfloat値に変換されること"""
        pp = make_pp(["--target-level", "-14.0"])

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-14.0)

    def test_short_flag_with_value(self, make_pp) -> None:
        """短縮フラグ-t -14.0がtarget_levelのfloat値に変換されること"""
        pp = make_pp(["-t", "-14.0"])

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-14.0)

    def test_bool_flag_without_value_becomes_true(self, make_pp) -> None:
        """bool型フラグが値なしでTrueになること"""
        pp = make_pp(["--dual-mono"])

        result = pp._build_normalize_kwargs()

        assert result["dual_mono"] is True

    def test_string_param(self, make_pp) -> None:
        """文字列パラメータ-c:a aacがそのまま文字列として保持されること"""
        pp = make_pp(["-c:a", "aac"])

        result = pp._build_normalize_kwargs()

        assert result["audio_codec"] == "aac"

    def test_unknown_flag_ignored(self, make_pp) -> None:
        """未知のフラグが無視されること"""
        pp = make_pp(["--unknown-flag", "value"])

        result = pp._build_normalize_kwargs()

        assert "unknown_flag" not in result

    def test_multiple_params(self, make_pp) -> None:
        """複数パラメータが同時に指定できること"""
        pp = make_pp(["-t", "-14.0", "-c:a", "aac", "-b:a", "128k"])

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-14.0)
        assert result["audio_codec"] == "aac"
        assert result["audio_bitrate"] == "128k"

    def test_non_bool_flag_at_end_warns(self, make_pp) -> None:
        """非boolフラグが末尾にあり値がない場合に警告が出ること"""
        pp = make_pp(["-t"])
        pp._build_normalize_kwargs()
        pp.report_warning.assert_called_once_with("引数の値がありません: -t")


# === --use-postprocessor kwargs ===


class TestUsePostprocessorKwargs:
    """--use-postprocessor経由のkwargsを処理すること

    --use-postprocessor "AudioNormalize:target_level=-14.0;audio_codec=aac"
    形式で渡されたパラメータを型変換してFFmpegNormalizeに渡すこと
    """

    def test_kwargs_stored_in_init(self) -> None:
        """kwargsが文字列のまま_kwargsに保存されること"""
        pp = AudioNormalizePP(target_level="-14.0")

        assert pp._kwargs == {"target_level": "-14.0"}

    def test_kwargs_float_conversion(self, make_pp) -> None:
        """文字列"-14.0"がfloat(-14.0)に型変換されること"""
        pp = make_pp(target_level="-14.0")

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-14.0)

    @pytest.mark.parametrize("val", ["true", "1", "yes", "True", "YES"])
    def test_kwargs_bool_truthy_string_converted_to_true(self, make_pp, val) -> None:
        """真を表す文字列("true", "1", "yes"等)がbool Trueに変換されること"""
        pp = make_pp(dual_mono=val)

        result = pp._build_normalize_kwargs()

        assert result["dual_mono"] is True

    @pytest.mark.parametrize("val", ["false", "0", "no"])
    def test_kwargs_bool_falsy_string_converted_to_false(self, make_pp, val) -> None:
        """偽を表す文字列("false", "0", "no")がbool Falseに変換されること"""
        pp = make_pp(dual_mono=val)

        result = pp._build_normalize_kwargs()

        assert result["dual_mono"] is False

    def test_ppa_overrides_kwargs(self, make_pp) -> None:
        """PPA引数とkwargsの両方が指定された場合、PPA引数が優先されること"""
        pp = make_pp(["-t", "-20.0"], target_level="-14.0")

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-20.0)

    def test_kwargs_only_when_no_ppa(self, make_pp) -> None:
        """PPA引数がない場合はkwargsのみが使用されること"""
        pp = make_pp([], target_level="-14.0", audio_codec="aac")

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-14.0)
        assert result["audio_codec"] == "aac"

    def test_unknown_kwargs_ignored(self, make_pp) -> None:
        """FFmpegNormalizeに存在しないパラメータ名が無視されること"""
        pp = make_pp(unknown_param="value")

        result = pp._build_normalize_kwargs()

        assert "unknown_param" not in result

    # --- フラグ形式のkwargsキー ---

    def test_short_flag_as_kwargs_key(self, make_pp) -> None:
        """kwargsのキーに短縮フラグ(-t, -c:a)が使用できること"""
        pp = make_pp(**{"-t": "-7.0", "-c:a": "aac"})

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-7.0)
        assert result["audio_codec"] == "aac"

    def test_long_flag_as_kwargs_key(self, make_pp) -> None:
        """kwargsのキーに長形式フラグ(--target-level)が使用できること"""
        pp = make_pp(**{"--target-level": "-7.0", "--audio-codec": "aac"})

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-7.0)
        assert result["audio_codec"] == "aac"

    def test_short_flag_bool_as_kwargs_key(self, make_pp) -> None:
        """短縮フラグをキーにしてbool型の文字列変換も動作すること"""
        pp = make_pp(**{"-vn": "true"})

        result = pp._build_normalize_kwargs()

        assert result["video_disable"] is True

    def test_mixed_flag_and_param_name_kwargs(self, make_pp) -> None:
        """短縮フラグ、パラメータ名、長形式フラグを混在して指定できること"""
        pp = make_pp(**{"-t": "-7.0", "audio_codec": "aac", "-b:a": "128k"})

        result = pp._build_normalize_kwargs()

        assert result["target_level"] == pytest.approx(-7.0)
        assert result["audio_codec"] == "aac"
        assert result["audio_bitrate"] == "128k"


# === _normalize_file ===


class TestNormalizeFile:
    """ファイル正規化を実行し安全性を保証すること

    一時ファイルに正規化結果を出力し、成功時のみ元ファイルを置換すること
    """

    def test_missing_file_skipped_with_warning(self, make_pp, tmp_path: Path) -> None:
        """存在しないファイルが警告付きでスキップされること"""
        pp = make_pp()
        info = {"filepath": str(tmp_path / "nonexistent.mp4")}

        pp._normalize_file(str(tmp_path / "nonexistent.mp4"), info)

        pp.report_warning.assert_called_once_with(
            f"ファイルが存在しません: {tmp_path / 'nonexistent.mp4'}"
        )

    @patch("yt_dlp_plugins.postprocessor.audio_normalize.FFmpegNormalize")
    def test_success_calls_normalization_pipeline(
        self, mock_ffmpeg_cls: MagicMock, make_pp, tmp_path: Path
    ) -> None:
        """正常時にadd_media_file -> run_normalizationのパイプラインが実行されること"""
        test_file = tmp_path / "test.mp4"
        test_file.write_bytes(b"original content")
        mock_norm = MagicMock()
        mock_ffmpeg_cls.return_value = mock_norm
        pp = make_pp()
        info = {"filepath": str(test_file), "ext": "mp4", "acodec": "aac"}

        pp._normalize_file(str(test_file), info)

        mock_norm.add_media_file.assert_called_once()
        mock_norm.run_normalization.assert_called_once()

    @patch("yt_dlp_plugins.postprocessor.audio_normalize.FFmpegNormalize")
    def test_failure_preserves_original(
        self, mock_ffmpeg_cls: MagicMock, make_pp, tmp_path: Path
    ) -> None:
        """正規化失敗時に元ファイルの内容が保持され、警告が出ること"""
        test_file = tmp_path / "test.mp4"
        test_file.write_bytes(b"original content")
        mock_norm = MagicMock()
        mock_norm.run_normalization.side_effect = FFmpegNormalizeError(
            "normalization failed"
        )
        mock_ffmpeg_cls.return_value = mock_norm
        pp = make_pp()
        info = {"filepath": str(test_file), "ext": "mp4", "acodec": "aac"}

        pp._normalize_file(str(test_file), info)

        assert test_file.read_bytes() == b"original content"
        pp.report_warning.assert_called_once_with(
            "音量正規化に失敗しました: normalization failed"
        )

    @patch("yt_dlp_plugins.postprocessor.audio_normalize.FFmpegNormalize")
    def test_unexpected_error_cleans_up_tmp(
        self, mock_ffmpeg_cls: MagicMock, make_pp, tmp_path: Path
    ) -> None:
        """予期しない例外でも一時ファイルが削除されること"""
        test_file = tmp_path / "test.mp4"
        test_file.write_bytes(b"original content")
        mock_ffmpeg_cls.side_effect = TypeError("unexpected")
        pp = make_pp()
        info = {"filepath": str(test_file), "ext": "mp4", "acodec": "aac"}

        with pytest.raises(TypeError, match="unexpected"):
            pp._normalize_file(str(test_file), info)

        assert test_file.read_bytes() == b"original content"
        tmp_files = list(tmp_path.glob("*.mp4"))
        assert tmp_files == [test_file]

    @patch("yt_dlp_plugins.postprocessor.audio_normalize.FFmpegNormalize")
    def test_inferred_defaults_passed_to_ffmpeg_normalize(
        self, mock_ffmpeg_cls: MagicMock, make_pp, tmp_path: Path
    ) -> None:
        """info辞書から推定したデフォルト値がFFmpegNormalizeに渡されること"""
        test_file = tmp_path / "test.opus"
        test_file.write_bytes(b"content")
        mock_norm = MagicMock()
        mock_ffmpeg_cls.return_value = mock_norm
        pp = make_pp()
        info = {
            "filepath": str(test_file),
            "ext": "opus",
            "acodec": "opus",
            "asr": 44100,
            "abr": 128.0,
        }

        pp._normalize_file(str(test_file), info)

        call_kwargs = mock_ffmpeg_cls.call_args[1]
        assert call_kwargs["extension"] == "opus"
        assert call_kwargs["audio_codec"] == "libopus"
        assert call_kwargs["sample_rate"] == 44100
        assert call_kwargs["audio_bitrate"] == "128k"

    @patch("yt_dlp_plugins.postprocessor.audio_normalize.FFmpegNormalize")
    def test_user_specified_overrides_inferred(
        self, mock_ffmpeg_cls: MagicMock, make_pp, tmp_path: Path
    ) -> None:
        """ユーザー指定(CLI/PPA)が自動推定より優先されること"""
        test_file = tmp_path / "test.opus"
        test_file.write_bytes(b"content")
        mock_norm = MagicMock()
        mock_ffmpeg_cls.return_value = mock_norm
        pp = make_pp(audio_codec="aac", extension="m4a", sample_rate="44100")
        info = {"filepath": str(test_file), "ext": "opus", "acodec": "opus"}

        pp._normalize_file(str(test_file), info)

        call_kwargs = mock_ffmpeg_cls.call_args[1]
        assert call_kwargs["audio_codec"] == "aac"
        assert call_kwargs["extension"] == "m4a"
        assert call_kwargs["sample_rate"] == 44100

    @patch("yt_dlp_plugins.postprocessor.audio_normalize.FFmpegNormalize")
    def test_no_metadata_backward_compatible(
        self, mock_ffmpeg_cls: MagicMock, make_pp, tmp_path: Path
    ) -> None:
        """メタデータ未提供時に後方互換性が保たれること"""
        test_file = tmp_path / "test.mp4"
        test_file.write_bytes(b"content")
        mock_norm = MagicMock()
        mock_ffmpeg_cls.return_value = mock_norm
        pp = make_pp()
        info = {"filepath": str(test_file)}

        pp._normalize_file(str(test_file), info)

        call_kwargs = mock_ffmpeg_cls.call_args[1]
        assert "extension" not in call_kwargs
        assert "audio_codec" not in call_kwargs
        assert call_kwargs["sample_rate"] == 48000
        assert "audio_bitrate" not in call_kwargs


# === run ===


class TestRun:
    """PostProcessorエントリポイントが正しく動作すること

    yt-dlpがダウンロード完了後に呼び出すrunメソッドが
    filepath の有無に応じて正規化を制御すること
    """

    def test_filepath_present_triggers_normalize(self, make_pp) -> None:
        """infoにfilepathが存在する場合、そのパスとinfo辞書で正規化が実行されること"""
        pp = make_pp()
        pp._normalize_file = MagicMock()
        info = {"filepath": "C:/downloads/test.mp4"}

        pp.run(info)

        pp._normalize_file.assert_called_once_with("C:/downloads/test.mp4", info)

    def test_without_filepath_skips(self, make_pp) -> None:
        """infoにfilepathが存在しない場合、正規化が実行されないこと"""
        pp = make_pp()
        pp._normalize_file = MagicMock()
        info: dict[str, str] = {}

        pp.run(info)

        pp._normalize_file.assert_not_called()

    def test_returns_empty_list_and_info(self, make_pp) -> None:
        """戻り値が([], info)であること"""
        pp = make_pp()
        pp._normalize_file = MagicMock()
        info = {"filepath": "C:/downloads/test.mp4"}

        result = pp.run(info)

        assert result == ([], info)


# === _CODEC_MAP ===


class TestCodecMap:
    """デコーダ名からエンコーダ名への変換マッピングが正しいこと"""

    @pytest.mark.parametrize(
        "decoder, encoder",
        [
            ("opus", "libopus"),
            ("vorbis", "libvorbis"),
            ("mp3", "libmp3lame"),
        ],
    )
    def test_codec_map_entries(self, decoder: str, encoder: str) -> None:
        """_CODEC_MAPの各エントリが正しいエンコーダ名を返すこと"""
        assert AudioNormalizePP._CODEC_MAP[decoder] == encoder


# === _infer_defaults ===


class TestInferDefaults:
    """_InfoDictからFFmpegNormalizeのデフォルト値を推定すること"""

    def test_ext_and_acodec_both_present(self) -> None:
        """ext, acodec, asr, abr の全てがある場合に正しく設定されること"""
        info = {"ext": "opus", "acodec": "opus", "asr": 44100, "abr": 128.0}

        result = AudioNormalizePP._infer_defaults(info)

        assert result["extension"] == "opus"
        assert result["audio_codec"] == "libopus"
        assert result["sample_rate"] == 44100
        assert result["audio_bitrate"] == "128k"

    @pytest.mark.parametrize(
        "acodec, expected_encoder",
        [
            ("opus", "libopus"),
            ("vorbis", "libvorbis"),
            ("mp3", "libmp3lame"),
        ],
    )
    def test_codec_requiring_mapping(self, acodec: str, expected_encoder: str) -> None:
        """マッピングが必要なコーデックが正しく変換されること"""
        info = {"ext": "test", "acodec": acodec}

        result = AudioNormalizePP._infer_defaults(info)

        assert result["audio_codec"] == expected_encoder

    @pytest.mark.parametrize("acodec", ["aac", "flac", "alac", "pcm_s16le"])
    def test_codec_not_requiring_mapping(self, acodec: str) -> None:
        """マッピング不要なコーデックがそのまま通ること"""
        info = {"ext": "test", "acodec": acodec}

        result = AudioNormalizePP._infer_defaults(info)

        assert result["audio_codec"] == acodec

    def test_acodec_none_skips_audio_codec(self) -> None:
        """acodec が "none" の場合に audio_codec がスキップされること"""
        info = {"ext": "mp4", "acodec": "none"}

        result = AudioNormalizePP._infer_defaults(info)

        assert "audio_codec" not in result
        assert result["extension"] == "mp4"

    def test_missing_ext_skips_extension(self) -> None:
        """ext が欠損している場合に extension がスキップされること"""
        info = {"acodec": "aac"}

        result = AudioNormalizePP._infer_defaults(info)

        assert "extension" not in result
        assert result["audio_codec"] == "aac"

    def test_missing_acodec_skips_audio_codec(self) -> None:
        """acodec が欠損している場合に audio_codec がスキップされること"""
        info = {"ext": "mp4"}

        result = AudioNormalizePP._infer_defaults(info)

        assert "audio_codec" not in result
        assert result["extension"] == "mp4"

    def test_empty_info_returns_only_sample_rate(self) -> None:
        """空の情報辞書では sample_rate のみが返されること"""
        info = {}

        result = AudioNormalizePP._infer_defaults(info)

        assert result == {"sample_rate": 48000}

    def test_asr_sets_sample_rate(self) -> None:
        """asr が存在する場合にその値が sample_rate に設定されること"""
        info = {"ext": "mp3", "acodec": "mp3", "asr": 44100}

        result = AudioNormalizePP._infer_defaults(info)

        assert result["sample_rate"] == 44100

    def test_asr_fallback_to_default(self) -> None:
        """asr がない場合に 48000 にフォールバックされること"""
        info = {"ext": "mp3", "acodec": "mp3"}

        result = AudioNormalizePP._infer_defaults(info)

        assert result["sample_rate"] == 48000

    def test_abr_sets_audio_bitrate(self) -> None:
        """abr から "128k" 形式の audio_bitrate が設定されること"""
        info = {"ext": "mp3", "acodec": "mp3", "abr": 128.0}

        result = AudioNormalizePP._infer_defaults(info)

        assert result["audio_bitrate"] == "128k"

    def test_abr_rounds_to_int(self) -> None:
        """abr が小数の場合に整数に切り捨てられること"""
        info = {"ext": "mp3", "acodec": "mp3", "abr": 128.5}

        result = AudioNormalizePP._infer_defaults(info)

        assert result["audio_bitrate"] == "128k"

    def test_missing_abr_skips_audio_bitrate(self) -> None:
        """abr がない場合に audio_bitrate がスキップされること"""
        info = {"ext": "mp3", "acodec": "mp3"}

        result = AudioNormalizePP._infer_defaults(info)

        assert "audio_bitrate" not in result


# === _SHORT_FLAGS ===


class TestShortFlags:
    """短縮フラグと長形式フラグが整合していること

    _SHORT_FLAGSで定義された全ての短縮フラグが
    対応する長形式フラグと一貫したマッピングを持つこと
    """

    def test_all_short_flags_have_corresponding_long_flag(self) -> None:
        """全ての短縮フラグに対応する長形式フラグがパラメータマップに存在すること"""
        param_map = AudioNormalizePP._build_param_map()

        for flag, param_name in AudioNormalizePP._SHORT_FLAGS.items():
            long_flag = "--" + param_name.replace("_", "-")
            assert long_flag in param_map, f"{flag} -> {long_flag} が見つからない"

    def test_short_and_long_flag_map_to_same_param(self) -> None:
        """短縮フラグと長形式フラグが同じパラメータ名と型にマッピングされること"""
        param_map = AudioNormalizePP._build_param_map()

        for flag, param_name in AudioNormalizePP._SHORT_FLAGS.items():
            long_flag = "--" + param_name.replace("_", "-")
            assert param_map[flag] == param_map[long_flag]


# === プラグイン検出 ===


class TestPluginDiscovery:
    """yt-dlpプラグインシステムに自動検出されること

    yt-dlpがPostProcessorプラグインとして正しく認識するための
    全ての条件を満たすこと
    """

    def test_module_is_importable(self) -> None:
        """モジュールがインポート可能でAudioNormalizePPクラスが公開されていること"""
        assert hasattr(yt_dlp_plugins.postprocessor.audio_normalize, "AudioNormalizePP")

    def test_is_subclass_of_postprocessor(self) -> None:
        """PostProcessorのサブクラスであること"""
        assert issubclass(AudioNormalizePP, PostProcessor)

    def test_class_name_ends_with_pp(self) -> None:
        """クラス名がPPで終わること"""
        assert AudioNormalizePP.__name__.endswith("PP")

    def test_discovered_by_yt_dlp_plugin_system(self) -> None:
        """yt-dlpのプラグインレジストリに自動登録されること"""
        with YoutubeDL({"quiet": True}):
            pass

        assert "AudioNormalizePP" in plugin_pps.value

    def test_discovered_class_has_correct_module(self) -> None:
        """正しいモジュールパスで登録されること"""
        with YoutubeDL({"quiet": True}):
            pass

        cls = plugin_pps.value["AudioNormalizePP"]
        assert cls.__module__ == "yt_dlp_plugins.postprocessor.audio_normalize"
