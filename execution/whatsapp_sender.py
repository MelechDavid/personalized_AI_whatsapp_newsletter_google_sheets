"""
WhatsApp Web Selenium automation module.

Connects to an existing Chrome instance (remote debugging) and sends
messages with image attachments via web.whatsapp.com.
"""

import os
import socket
import subprocess
import time

import pyautogui
import pyperclip

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager


# --- Custom exceptions ---

class WhatsAppSendError(Exception):
    """Base exception for send failures."""
    pass

class ContactNotFoundError(WhatsAppSendError):
    """Phone number not on WhatsApp."""
    pass

class SendTimeoutError(WhatsAppSendError):
    """Timed out waiting for an element."""
    pass


# --- Selector registry ---
# Centralized so they can be updated when WhatsApp Web changes its DOM.
# Multiple fallbacks per element for resilience.

SELECTORS = {
    "message_input": [
        (By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="10"]'),
        (By.CSS_SELECTOR, 'div[contenteditable="true"][title="Type a message"]'),
        (By.CSS_SELECTOR, 'footer div[contenteditable="true"]'),
    ],
    "attach_button": [
        (By.CSS_SELECTOR, 'span[data-icon="plus-rounded"]'),
        (By.CSS_SELECTOR, 'div[title="Attach"]'),
        (By.CSS_SELECTOR, 'span[data-icon="plus"]'),
        (By.CSS_SELECTOR, 'span[data-icon="attach-menu-plus"]'),
        (By.CSS_SELECTOR, 'div[aria-label="Attach"]'),
    ],
    "image_input": [
        (By.CSS_SELECTOR, 'input[accept="image/*,video/mp4,video/3gpp,video/quicktime"]'),
        (By.CSS_SELECTOR, 'input[accept*="image/*"]'),
        (By.XPATH, '//input[@type="file" and contains(@accept, "image")]'),
    ],
    "caption_input": [
        (By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="undefined"]'),
        (By.XPATH, '//div[@contenteditable="true" and @data-tab="undefined" and @role="textbox"]'),
        (By.XPATH, '//div[@contenteditable="true" and contains(@aria-placeholder, "caption")]'),
        (By.XPATH, '//div[@contenteditable="true" and contains(@aria-placeholder, "Add a")]'),
    ],
    "send_button": [
        (By.CSS_SELECTOR, 'span[data-icon="wds-ic-send-filled"]'),
        (By.CSS_SELECTOR, 'div[aria-label="Send"]'),
        (By.CSS_SELECTOR, 'span[data-icon="send"]'),
        (By.CSS_SELECTOR, 'div[role="button"][aria-label="Send"]'),
    ],
    "invalid_phone_popup": [
        (By.XPATH, '//*[contains(text(), "Phone number shared via url is invalid")]'),
        (By.XPATH, '//*[contains(text(), "phone number shared via url is invalid")]'),
    ],
    "popup_ok_button": [
        (By.XPATH, '//div[@role="button" and .//div[text()="OK"]]'),
        (By.XPATH, '//div[contains(@class, "popup")]//div[@role="button"]'),
    ],
    "continue_to_chat": [
        (By.XPATH, '//div[@role="button" and .//div[text()="Continue to Chat"]]'),
        (By.XPATH, '//*[contains(text(), "Continue to Chat")]'),
    ],
    "photos_and_videos": [
        (By.CSS_SELECTOR, 'div[aria-label="Photos & videos"]'),
        (By.XPATH, '//div[@role="listitem" and .//span[text()="Photos & videos"]]'),
        (By.XPATH, '//*[contains(text(), "Photos & videos")]'),
    ],
}


def _is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def ensure_chrome_ready(
    debug_port: int = 9222,
    chrome_path: str | None = None,
    profile_dir: str | None = None,
    launch_timeout: int = 15,
):
    """
    Make sure a Chrome instance with remote debugging is reachable.
    If the port is not open, launch Chrome automatically with a
    dedicated automation profile so it never merges into an
    already-running Chrome.
    """
    if _is_port_open(debug_port):
        return  # Chrome already listening

    if chrome_path is None:
        chrome_path = os.getenv(
            "CHROME_PATH",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )

    if profile_dir is None:
        from pathlib import Path
        profile_dir = str(Path(__file__).parent.parent / ".tmp" / "chrome-whatsapp")

    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        chrome_path,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    subprocess.Popen(cmd)

    # Wait for the debugging port to become reachable
    for _ in range(launch_timeout * 2):
        if _is_port_open(debug_port):
            return
        time.sleep(0.5)

    raise RuntimeError(
        f"Chrome did not start with remote-debugging on port {debug_port} "
        f"within {launch_timeout}s.  Check CHROME_PATH in .env."
    )


def create_driver(
    debug_port: int = 9222,
    chrome_path: str | None = None,
    profile_dir: str | None = None,
) -> webdriver.Chrome:
    """
    Connect to Chrome with remote debugging, launching it automatically
    if it is not already running on the debugging port.
    """
    ensure_chrome_ready(debug_port, chrome_path, profile_dir)

    options = Options()
    options.debugger_address = f"127.0.0.1:{debug_port}"

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def find_element_with_fallbacks(driver, selector_key: str, timeout: int = 10):
    """Try multiple selectors, return the first element found."""
    selectors = SELECTORS[selector_key]
    last_exception = None

    for by, value in selectors:
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException as e:
            last_exception = e
            continue

    raise TimeoutException(
        f"Could not find element '{selector_key}' with any selector. "
        f"Last error: {last_exception}"
    )


def find_clickable_with_fallbacks(driver, selector_key: str, timeout: int = 10):
    """Try multiple selectors, return the first clickable element found."""
    selectors = SELECTORS[selector_key]
    last_exception = None

    for by, value in selectors:
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            return element
        except TimeoutException as e:
            last_exception = e
            continue

    raise TimeoutException(
        f"Could not find clickable element '{selector_key}'. "
        f"Last error: {last_exception}"
    )


def send_whatsapp_message(
    driver: webdriver.Chrome,
    phone_clean: str,
    caption: str,
    image_path: str,
    timeout: int = 30,
) -> bool:
    """
    Send a WhatsApp message with image and caption to a phone number.

    Returns True if message sent successfully.
    Raises ContactNotFoundError if phone is not on WhatsApp.
    Raises SendTimeoutError if any step times out.
    """

    # Step 1: Navigate to chat via direct URL
    url = f"https://web.whatsapp.com/send?phone={phone_clean}"
    driver.get(url)

    # Step 2: Wait for chat to load or error popup
    chat_loaded = False

    for _ in range(timeout * 2):  # Check every 0.5s
        # Check for error popup (fast fail)
        try:
            for by, value in SELECTORS["invalid_phone_popup"]:
                elements = driver.find_elements(by, value)
                if elements:
                    _dismiss_popup(driver)
                    raise ContactNotFoundError(
                        f"Phone {phone_clean} is not on WhatsApp"
                    )
        except ContactNotFoundError:
            raise
        except Exception:
            pass

        # Check for "Continue to Chat" button (unsaved contacts)
        try:
            for by, value in SELECTORS["continue_to_chat"]:
                elements = driver.find_elements(by, value)
                if elements:
                    elements[0].click()
                    time.sleep(1)
                    break
        except Exception:
            pass

        # Check if chat loaded (message input present)
        try:
            for by, value in SELECTORS["message_input"]:
                elements = driver.find_elements(by, value)
                if elements:
                    chat_loaded = True
                    break
        except Exception:
            pass

        if chat_loaded:
            break
        time.sleep(0.5)

    if not chat_loaded:
        raise SendTimeoutError(
            f"Chat did not load for phone {phone_clean} within {timeout}s"
        )

    time.sleep(1)  # Let WhatsApp finish rendering

    # Step 3: Click attachment button
    attach_btn = find_clickable_with_fallbacks(driver, "attach_button", timeout=10)
    attach_btn.click()
    time.sleep(1)

    # Step 3b: Click "Photos & videos" menu item
    photos_btn = find_clickable_with_fallbacks(driver, "photos_and_videos", timeout=5)
    photos_btn.click()
    time.sleep(2)  # Wait for native file dialog to open

    # Step 4: Paste file path into native Windows file dialog and press Enter
    image_abs_path = os.path.abspath(image_path)
    pyperclip.copy(image_abs_path)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)
    pyautogui.press('enter')

    # Step 5: Wait for image preview with caption box
    time.sleep(4)

    # Step 6: Type caption in the preview caption box
    caption_box = find_element_with_fallbacks(driver, "caption_input", timeout=10)
    driver.execute_script("arguments[0].focus();", caption_box)
    time.sleep(0.3)
    _type_message(driver, caption_box, caption)
    time.sleep(0.5)

    # Step 7: Click send
    send_btn = find_element_with_fallbacks(driver, "send_button", timeout=10)
    driver.execute_script("arguments[0].click();", send_btn)

    # Step 8: Verify message was sent (preview overlay closes)
    time.sleep(5)
    try:
        find_element_with_fallbacks(driver, "message_input", timeout=10)
        return True
    except TimeoutException:
        raise SendTimeoutError("Could not verify message was sent")


def _type_message(driver, element, text: str):
    """
    Type text into a contenteditable div using clipboard paste.
    More reliable than send_keys() on React contenteditable inputs.
    """
    script = """
    const el = arguments[0];
    const text = arguments[1];
    el.focus();
    const dataTransfer = new DataTransfer();
    dataTransfer.setData('text/plain', text);
    const pasteEvent = new ClipboardEvent('paste', {
        clipboardData: dataTransfer,
        bubbles: true,
        cancelable: true,
    });
    el.dispatchEvent(pasteEvent);
    """
    try:
        driver.execute_script(script, element, text)
    except Exception:
        # Fallback: use send_keys
        element.clear()
        element.send_keys(text)


def _dismiss_popup(driver):
    """Dismiss an error popup by clicking OK or pressing Escape."""
    try:
        ok_btn = find_clickable_with_fallbacks(driver, "popup_ok_button", timeout=5)
        ok_btn.click()
        time.sleep(0.5)
    except TimeoutException:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.5)


def is_whatsapp_connected(driver) -> bool:
    """Check if WhatsApp Web is still connected (not showing QR code)."""
    try:
        qr = driver.find_elements(
            By.CSS_SELECTOR, 'canvas[aria-label="Scan this QR code to link a device!"]'
        )
        disconnect = driver.find_elements(
            By.XPATH, '//*[contains(text(), "Phone not connected")]'
        )
        return len(qr) == 0 and len(disconnect) == 0
    except Exception:
        return False


def diagnose_whatsapp_dom(driver) -> dict:
    """
    Inspect current WhatsApp Web DOM to discover working selectors.
    Run this when selectors break to find updated equivalents.
    """
    results = {}

    editables = driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
    results["contenteditable_divs"] = [
        {
            "data-tab": e.get_attribute("data-tab"),
            "title": e.get_attribute("title"),
            "aria-label": e.get_attribute("aria-label"),
            "class": (e.get_attribute("class") or "")[:80],
        }
        for e in editables
    ]

    icons = driver.find_elements(By.CSS_SELECTOR, 'span[data-icon]')
    results["data_icons"] = sorted(set(
        e.get_attribute("data-icon") for e in icons
    ))

    file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
    results["file_inputs"] = [
        {"accept": e.get_attribute("accept")}
        for e in file_inputs
    ]

    return results
