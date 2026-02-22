"""
DOM diagnostic — captures WhatsApp Web DOM at each attachment stage.
Run: python execution/diagnose_dom.py
"""
import sys, time, os
from pathlib import Path

import pyautogui
import pyperclip

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from execution.whatsapp_sender import create_driver
from selenium.webdriver.common.by import By


def safe_attr(el, attr):
    try:
        return el.get_attribute(attr)
    except Exception:
        return None


def snapshot(driver, label):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    try:
        icons = driver.find_elements(By.CSS_SELECTOR, 'span[data-icon]')
        icon_names = sorted(set(filter(None, (safe_attr(e, "data-icon") for e in icons))))
        print(f"\ndata-icons ({len(icon_names)}):")
        for ic in icon_names:
            print(f"  - {ic}")
    except Exception as e:
        print(f"\ndata-icons: ERROR {e}")

    try:
        editables = driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
        print(f"\ncontenteditable divs ({len(editables)}):")
        for e in editables:
            print(f"  data-tab={safe_attr(e,'data-tab')!r}  "
                  f"aria-label={safe_attr(e,'aria-label')!r}  "
                  f"role={safe_attr(e,'role')!r}  "
                  f"placeholder={safe_attr(e,'aria-placeholder')!r}")
    except Exception as e:
        print(f"\ncontenteditable: ERROR {e}")

    try:
        file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        print(f"\nfile inputs ({len(file_inputs)}):")
        for fi in file_inputs:
            print(f"  accept={safe_attr(fi,'accept')!r}  displayed={fi.is_displayed()}")
    except Exception as e:
        print(f"\nfile inputs: ERROR {e}")

    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, 'span[data-icon], button, [role="button"]')
        relevant = []
        for b in buttons:
            t = safe_attr(b, "title") or ""
            a = safe_attr(b, "aria-label") or ""
            di = safe_attr(b, "data-icon") or ""
            txt = (b.text or "")[:60].replace("\n", " ")
            if any(k in (t+a+txt+di).lower() for k in ["send","photo","video","attach","document","camera","add file","caption"]):
                relevant.append(f"  <{b.tag_name}> data-icon={di!r} title={t!r} aria-label={a!r} text={txt!r}")
        if relevant:
            print(f"\nRelevant buttons ({len(relevant)}):")
            for r in relevant:
                print(r)
    except Exception as e:
        print(f"\nbuttons: ERROR {e}")

    # Menu items (li, [role=menuitem], etc.)
    try:
        menu_items = driver.find_elements(By.CSS_SELECTOR, '[role="listitem"], li, [role="menuitem"], [role="option"]')
        if menu_items:
            print(f"\nMenu/list items ({len(menu_items)}):")
            for m in menu_items[:20]:
                txt = (m.text or "").strip()[:80].replace("\n", " ")
                aria = safe_attr(m, "aria-label") or ""
                if txt or aria:
                    print(f"  <{m.tag_name}> text={txt!r}  aria-label={aria!r}")
    except Exception:
        pass


def main():
    image_path = os.getenv("IMAGE_PATH", "")
    print(f"Image: {image_path} (exists={Path(image_path).exists()})")

    driver = create_driver()
    for h in driver.window_handles:
        driver.switch_to.window(h)
        if "web.whatsapp.com" in driver.current_url:
            break
    print(f"URL: {driver.current_url}")

    phone = input("\nPhone (digits only, e.g. 12223008640): ").strip()
    if phone:
        url = f"https://web.whatsapp.com/send?phone={phone}"
        print(f"Navigating to {url}")
        driver.get(url)

    input("\n>>> WAIT until chat is fully loaded in Chrome, then press Enter...")
    time.sleep(2)  # small extra settle time

    snapshot(driver, "STAGE 1: CHAT LOADED")
    input("\n>>> Press Enter to click + button...")

    try:
        plus = driver.find_element(By.CSS_SELECTOR, 'span[data-icon="plus-rounded"]')
        plus.click()
    except Exception:
        # Try clicking parent
        plus = driver.find_element(By.XPATH, '//*[@data-icon="plus-rounded"]/ancestor::div[@role="button"]')
        plus.click()
    time.sleep(2)

    snapshot(driver, "STAGE 2: MENU OPEN")
    input("\n>>> Press Enter to click Photos & videos (file dialog will open)...")

    photos = driver.find_element(By.CSS_SELECTOR, 'div[aria-label="Photos & videos"]')
    photos.click()
    time.sleep(2)  # Wait for native file dialog

    # Paste file path into native Windows dialog and press Enter
    image_abs = os.path.abspath(image_path)
    print(f"\nPasting file path into dialog: {image_abs}")
    pyperclip.copy(image_abs)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)
    pyautogui.press('enter')
    print("Pressed Enter — dialog should close, preview should appear.")

    input("\n>>> WAIT until image preview + caption box appear in Chrome, then press Enter...")
    time.sleep(2)

    snapshot(driver, "STAGE 3: IMAGE PREVIEW + CAPTION")

    # Step 4: Type caption into the preview caption box
    input("\n>>> Press Enter to type caption in caption box...")
    try:
        caption_box = driver.find_element(By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="undefined"]')
        print(f"Found caption box: data-tab={safe_attr(caption_box, 'data-tab')!r}  aria-label={safe_attr(caption_box, 'aria-label')!r}")
        driver.execute_script("arguments[0].focus();", caption_box)
        time.sleep(0.3)
        # Paste caption via JS ClipboardEvent
        test_caption = "Test caption from diagnostic script"
        script = """
        const el = arguments[0];
        const text = arguments[1];
        el.focus();
        const dt = new DataTransfer();
        dt.setData('text/plain', text);
        el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
        """
        driver.execute_script(script, caption_box, test_caption)
        time.sleep(1)
        print(f"Caption typed: {test_caption!r}")
    except Exception as e:
        print(f"ERROR typing caption: {e}")

    snapshot(driver, "STAGE 4: CAPTION TYPED")

    # Step 5: Click send button
    input("\n>>> Press Enter to click SEND button...")
    try:
        send_btn = driver.find_element(By.CSS_SELECTOR, 'div[aria-label="Send"]')
        print(f"Found send button: aria-label={safe_attr(send_btn, 'aria-label')!r}")
        driver.execute_script("arguments[0].click();", send_btn)
        print("Send button clicked!")
        time.sleep(3)
    except Exception as e:
        print(f"ERROR clicking send: {e}")
        # Fallback: try the icon
        try:
            send_icon = driver.find_element(By.CSS_SELECTOR, 'span[data-icon="wds-ic-send-filled"]')
            send_icon.click()
            print("Clicked send via icon fallback")
        except Exception as e2:
            print(f"Fallback also failed: {e2}")

    snapshot(driver, "STAGE 5: AFTER SEND")
    print("\n\nDONE — copy all output above and paste it back.")
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()