"""测试 app name mapping 数据与归一化查找."""

import pytest

from pymidscene.android.app_name_mapping import (
    DEFAULT_APP_NAME_MAPPING,
    resolve_package_name,
)


class TestAppNameMapping:
    def test_mapping_is_populated(self):
        assert len(DEFAULT_APP_NAME_MAPPING) > 150

    def test_resolve_chinese(self):
        assert resolve_package_name("小红书") == "com.xingin.xhs"
        assert resolve_package_name("微信") == "com.tencent.mm"

    def test_resolve_case_insensitive(self):
        # 所有大小写形式都能命中
        assert resolve_package_name("chrome") == "com.android.chrome"
        assert resolve_package_name("CHROME") == "com.android.chrome"
        assert resolve_package_name("Chrome") == "com.android.chrome"

    def test_resolve_space_insensitive(self):
        # 归一化会去空格
        assert (
            resolve_package_name("Google Maps")
            == resolve_package_name("googlemaps")
            == "com.google.android.apps.maps"
        )

    def test_resolve_unknown_returns_none(self):
        assert resolve_package_name("此应用并不存在") is None
        assert resolve_package_name("") is None

    def test_custom_mapping_overrides(self):
        custom = {"MyApp": "com.my.app"}
        assert resolve_package_name("MyApp", custom) == "com.my.app"
        # 不在自定义 table 中
        assert resolve_package_name("Chrome", custom) is None
