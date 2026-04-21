"""iOS app 名 → bundle id 映射测试."""

from pymidscene.ios.app_name_mapping import (
    DEFAULT_APP_NAME_MAPPING,
    resolve_bundle_id,
)


class TestIOSAppMapping:
    def test_mapping_is_populated(self):
        assert len(DEFAULT_APP_NAME_MAPPING) > 150

    def test_resolve_chinese(self):
        assert resolve_bundle_id("微信") == "com.tencent.xin"
        assert resolve_bundle_id("小红书") == "com.xingin.discover"
        assert resolve_bundle_id("Safari") == "com.apple.mobilesafari"

    def test_case_and_space_insensitive(self):
        assert (
            resolve_bundle_id("GoogleChrome")
            == resolve_bundle_id("google chrome")
            == "com.google.chrome.ios"
        )

    def test_unknown_returns_none(self):
        assert resolve_bundle_id("不存在的应用") is None
        assert resolve_bundle_id("") is None

    def test_custom_mapping_overrides(self):
        assert (
            resolve_bundle_id("MyApp", {"MyApp": "com.my.app"})
            == "com.my.app"
        )
        # 自定义 table 里没有 Safari
        assert resolve_bundle_id("Safari", {"MyApp": "com.my.app"}) is None
