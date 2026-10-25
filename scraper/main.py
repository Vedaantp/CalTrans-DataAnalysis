import sys
import os
import asyncio
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, BrowserContext
from pathlib import Path

load_dotenv()

BASE_URL = "https://pems.dot.ca.gov"
TARGET_URL = "/?dnode=Clearinghouse&type={type}&district_id={district_id}&submit=Submit"
TYPES = ["station_5min", "chp_incidents_day"]
DISCTRICTS = ["3", "4", "5", "6", "7", "8", "10", "11", "12"]
ALL_DISTRICTS = "all"
DATA = "data"
USERNAME = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

MAX_CONCURRENT_TASKS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)


async def login(page: Page) -> None:
    print("Navigating to login page")
    await page.goto(BASE_URL)

    await page.fill("input[name='username']", USERNAME)
    await page.fill("input[name='password']", PASSWORD)

    print("Logging into PeMS")
    await page.click("input[type='submit']")
    await page.wait_for_load_state("domcontentloaded")


async def get_target_page(page: Page, target_url: str) -> None:
    print(f"Loading target page: {target_url}")
    await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

    print("Waiting for content to load")
    await page.wait_for_selector("table a[href*='Clearinghouse']", timeout=60000)


async def download_data(page: Page, data_path: str) -> None:
    script_dir = Path(__file__).resolve().parent
    src_dir = script_dir.parent
    data_dir = src_dir / DATA / data_path
    os.makedirs(data_dir, exist_ok=True)

    files = page.locator("table a[href*='download'][href*='Clearinghouse']")
    file_count = await files.count()

    print(f"[{data_path}] Processing {file_count} files")

    for i in range(file_count):
        file = files.nth(i)
        link_text = await file.text_content()
        link_text = link_text.strip()
        safe_name = link_text.replace(" ", "-")

        print(f"[{data_path}] File {i + 1}/{file_count}: Downloading {safe_name}")

        try:
            async with page.expect_download() as download_info:
                await file.click()
            download = await download_info.value
            await download.save_as(data_dir / safe_name)
        except Exception as e:
            print(f"[{data_path}] Error downloading {safe_name}: {e}")


async def process_district_task(
    context: BrowserContext, type: str, district_id: str
) -> None:
    async with semaphore:
        page = await context.new_page()
        try:
            target_url = BASE_URL + TARGET_URL.format(
                type=type, district_id=district_id
            )
            data_path = f"{type}-{district_id}"

            await get_target_page(page, target_url)
            await download_data(page, data_path)
        finally:
            await page.close()


async def scrape() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        login_page = await context.new_page()
        await login(login_page)
        await login_page.close()

        tasks = []

        for type in TYPES:
            if type == "chp_incidents_day":
                tasks.append(process_district_task(context, type, ALL_DISTRICTS))
            else:
                for district_id in DISCTRICTS:
                    tasks.append(process_district_task(context, type, district_id))

        print(f"Dispatched {len(tasks)} target jobs to execution queue...")
        await asyncio.gather(*tasks)

        await context.close()
        await browser.close()


def main() -> int:
    asyncio.run(scrape())
    return 0


if __name__ == "__main__":
    sys.exit(main())
