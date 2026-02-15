"""AudioNormalizePPの仕様テスト

このテストスイートはAudioNormalizePPの全機能を以下の観点で検証する:

1. 型ヒント解析(_extract_scalar_type):
   FFmpegNormalize.__init__の型アノテーションからスカラー型を抽出する仕組み

2. フラグ-パラメータマッピング構築(_build_param_map):
   CLIフラグ(--target-level, -t等)からパラメータ名と型へのマッピング自動生成

3. PPA引数パース(_build_normalize_kwargs):
   --ppa "AudioNormalize:ARGS" 形式のCLI引数をパースしてkwargsに変換

4. --use-postprocessor kwargs:
   --use-postprocessor "AudioNormalize:key=value" 形式のパラメータ処理と型変換

5. ファイル正規化(_normalize_file):
   ffmpeg-normalizeによる音量正規化の実行とエラー時の安全性保証

6. PostProcessorエントリポイント(run):
   yt-dlpから呼び出されるメインエントリポイントの振る舞い

7. 短縮フラグ整合性(_SHORT_FLAGS):
   短縮フラグと長形式フラグの一貫性

8. プラグイン検出:
   yt-dlpプラグインシステムによる自動検出の正当性
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
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

        pp._normalize_file(str(tmp_path / "nonexistent.mp4"))

        pp.report_warning.assert_called_once()

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

        pp._normalize_file(str(test_file))

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

        pp._normalize_file(str(test_file))

        assert test_file.read_bytes() == b"original content"
        pp.report_warning.assert_called_once()


# === run ===


class TestRun:
    """PostProcessorエントリポイントが正しく動作すること

    yt-dlpがダウンロード完了後に呼び出すrunメソッドが
    filepath の有無に応じて正規化を制御すること
    """

    def test_filepath_present_triggers_normalize(self, make_pp) -> None:
        """infoにfilepathが存在する場合、そのパスで正規化が実行されること"""
        pp = make_pp()
        pp._normalize_file = MagicMock()
        info = {"filepath": "C:/downloads/test.mp4"}

        pp.run(info)

        pp._normalize_file.assert_called_once_with("C:/downloads/test.mp4")

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
