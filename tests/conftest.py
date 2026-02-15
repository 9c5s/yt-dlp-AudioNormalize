from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from yt_dlp_plugins.postprocessor.audio_normalize import AudioNormalizePP


@pytest.fixture()
def make_pp():
    """AudioNormalizePPのテスト用ファクトリフィクスチャ

    外部依存(yt-dlpのUI出力, PPA設定取得)をモックに差し替えた
    AudioNormalizePPインスタンスを生成する

    Args:
        ppa_args: --ppa "AudioNormalize:..." 経由で渡されるCLI引数リスト
        例: ["-t", "-14.0", "-c:a", "aac"]
        **kwargs: --use-postprocessor "AudioNormalize:key=value" 経由のパラメータ
        例: target_level="-14.0", audio_codec="aac"

    モック対象:
        to_screen: 進捗メッセージ出力(実際の出力を抑制)
        report_warning: 警告メッセージ出力(呼び出し検証用)
        _configuration_args: PPA引数の取得(テストから任意の引数を注入可能にする)
    """

    def _factory(ppa_args=None, **kwargs):
        pp = AudioNormalizePP(**kwargs)
        pp.to_screen = MagicMock()
        pp.report_warning = MagicMock()
        pp._configuration_args = MagicMock(return_value=ppa_args or [])
        return pp

    return _factory
