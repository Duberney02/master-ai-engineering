from app.config import get_settings


def pytest_runtest_setup(item):
    get_settings.cache_clear()


def pytest_runtest_teardown(item, nextitem):
    get_settings.cache_clear()
