"""Unit tests for the safe async runner and profile resolution."""

import asyncio

import pytest

from tools.fetcher import PageFetcher, run_async


async def _return(value):
    return value


async def _boom():
    raise ValueError("kaboom")


def test_run_async_no_running_loop():
    assert run_async(_return(42)) == 42


def test_run_async_inside_running_loop():
    async def outer():
        # Calling run_async while a loop is already running must still work
        return run_async(_return("nested"))

    assert asyncio.run(outer()) == "nested"


def test_run_async_propagates_errors():
    with pytest.raises(ValueError, match="kaboom"):
        run_async(_boom())


def test_resolve_profile_none():
    assert PageFetcher._resolve_profile(None) is None
    assert PageFetcher._resolve_profile("") is None


def test_resolve_storage_state_disabled():
    assert PageFetcher._resolve_storage_state_path(None, auto_storage_state=False) is None


def test_fetcher_constructs_without_profile():
    fetcher = PageFetcher()
    assert fetcher.browser_profile is None
    assert fetcher.browser_name == "chromium"
