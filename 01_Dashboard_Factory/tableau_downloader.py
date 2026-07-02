"""
tableau_downloader.py
─────────────────────
Downloads a Tableau workbook (.twbx) from Tableau Server given any
dashboard/view URL. Handles Microsoft SSO / SAML automatically.

Usage
─────
    python tableau_downloader.py <tableau-url> --email your@email.com

    python tableau_downloader.py \\
        "https://usinsightreporting.cbre.com/#/site/WESCO/workbooks/56365/views" \\
        --email rajkumar.ganeshan@cbre.com \\
        --output ~/Downloads

Requirements
────────────
    pip install selenium webdriver-manager requests
"""

import argparse
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse, unquote, quote

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# ─── URL parser ───────────────────────────────────────────────────────────────

def parse_tableau_url(url: str):
    parsed   = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path     = parsed.fragment or parsed.path

    m = re.search(r"/workbooks/(\d+)", path)
    if m:
        workbook_id = m.group(1)
        site_m      = re.search(r"/site/([^/]+)", path)
        site        = unquote(site_m.group(1)) if site_m else "Default"
        return base_url, site, workbook_id

    raise ValueError(f"Cannot extract workbook ID from URL: {url}")


# ─── ChromeDriver finder ──────────────────────────────────────────────────────

def _find_chromedriver() -> str:
    wdm_root = os.path.expanduser("~/.wdm/drivers/chromedriver")
    found = []
    if os.path.isdir(wdm_root):
        for root, _dirs, files in os.walk(wdm_root):
            for fname in files:
                if fname == "chromedriver":
                    full = os.path.join(root, fname)
                    if not os.access(full, os.X_OK):
                        os.chmod(full, 0o755)
                    if os.access(full, os.X_OK):
                        found.append(full)
    if found:
        found.sort(reverse=True)
        return found[0]
    raise FileNotFoundError(
        "chromedriver not found. Run: pip install --upgrade webdriver-manager"
    )


# ─── Browser launch ───────────────────────────────────────────────────────────

def launch_browser(download_dir: str, headless: bool = False) -> webdriver.Chrome:
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("prefs", {
        "download.default_directory":         download_dir,
        "download.prompt_for_download":       False,
        "download.directory_upgrade":         True,
        "safebrowsing.enabled":               True,
        "plugins.always_open_pdf_externally": True,
    })
    driver_path = _find_chromedriver()
    print(f"  ChromeDriver : {driver_path}")
    service = ChromeService(executable_path=driver_path)
    driver  = webdriver.Chrome(service=service, options=opts)

    # CDP: force all downloads to our directory — Browser-scope covers every
    # tab and iframe, which Page-scope misses (Tableau opens downloads in new contexts)
    try:
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
            "behavior":      "allow",
            "downloadPath":  download_dir,
            "eventsEnabled": True,
        })
    except Exception:
        # Older Chrome: fall back to page-scoped command
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior":     "allow",
            "downloadPath": download_dir,
        })
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    })
    print(f"  Download dir : {download_dir}")
    return driver


# ─── Microsoft SSO login ──────────────────────────────────────────────────────

def _fill_ms_email(driver: webdriver.Chrome, email: str, wait_sec: int = 15):
    """Fill the Microsoft 'Enter email' step."""
    wait = WebDriverWait(driver, wait_sec)
    try:
        inp = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[type='email'], input[name='loginfmt']")))
        inp.clear()
        inp.send_keys(email)
        time.sleep(0.5)
        # Click Next / Submit
        try:
            btn = driver.find_element(By.CSS_SELECTOR,
                "input[type='submit'], button[type='submit'], #idSIButton9")
            btn.click()
        except Exception:
            inp.send_keys(Keys.RETURN)
        print(f"  ✓ Email entered: {email}")
        return True
    except Exception:
        return False


def _fill_ms_password(driver: webdriver.Chrome, password: str, wait_sec: int = 15):
    """Fill the Microsoft 'Enter password' step."""
    wait = WebDriverWait(driver, wait_sec)
    try:
        pw = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR,
             "input[type='password'], input[name='passwd'], input[id='i0118']")))
        pw.clear()
        pw.send_keys(password)
        time.sleep(0.5)
        try:
            btn = driver.find_element(By.CSS_SELECTOR,
                "input[type='submit'], button[type='submit'], #idSIButton9")
            btn.click()
        except Exception:
            pw.send_keys(Keys.RETURN)
        print("  ✓ Password entered")
        return True
    except Exception:
        return False


def _handle_stay_signed_in(driver: webdriver.Chrome, wait_sec: int = 2):
    """Dismiss 'Stay signed in?' prompt if it appears (short timeout — optional prompt)."""
    try:
        btn = WebDriverWait(driver, wait_sec).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "#idSIButton9, input[value='Yes'], button[value='yes']")))
        btn.click()
        print("  ✓ 'Stay signed in' dismissed")
    except Exception:
        pass


def selenium_login(driver: webdriver.Chrome, url: str,
                   email: str, password: str,
                   mfa_timeout: int = 60) -> None:
    """
    CBRE Okta SSO login flow (login.cbre.com) — optimised for speed.
    Every wait is condition-based; no fixed sleeps between steps.
    """
    OKTA_USERNAME = ("#okta-signin-username, input[name='identifier'], "
                     "input[name='username'], input[autocomplete='username']")
    OKTA_PASSWORD = ("#okta-signin-password, input[name='credentials.passcode'], "
                     "input[name='password'], input[type='password']")
    OKTA_SUBMIT   = ("#okta-signin-submit, input[type='submit'], "
                     "button[type='submit'][data-type='save'], button.button-primary")

    tableau_host = url.split("#")[0].rstrip("/")

    print(f"  Opening : {url}")
    driver.get(url)

    # ── Step 1: Wait for Okta redirect ────────────────────────────────────────
    print("  Waiting for Okta SSO redirect…")
    try:
        WebDriverWait(driver, 20).until(
            lambda d: "login.cbre.com" in d.current_url or "okta.com" in d.current_url
        )
        print(f"  ✓ On SSO page: {driver.current_url.split('?')[0]}")
    except Exception:
        print(f"  Current page: {driver.current_url.split('?')[0]}")

    # ── Step 2: Fill username — paste all at once, no per-char delay ──────────
    print(f"  Filling username: {email}")
    try:
        username_field = WebDriverWait(driver, 12).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, OKTA_USERNAME)))
        username_field.clear()
        username_field.send_keys(email)          # paste all at once — instant

        try:
            driver.find_element(By.CSS_SELECTOR, OKTA_SUBMIT).click()
        except Exception:
            username_field.send_keys(Keys.RETURN)
        print("  ✓ Username submitted")

    except Exception as e:
        print(f"  ⚠ Username field error ({e.__class__.__name__}) — fill manually")

    # ── Step 3: Password (if provided) — wait for field, no fixed sleep ───────
    if password:
        print("  Waiting for password field…")
        try:
            pw_field = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, OKTA_PASSWORD)))
            pw_field.clear()
            pw_field.send_keys(password)
            try:
                driver.find_element(By.CSS_SELECTOR, OKTA_SUBMIT).click()
            except Exception:
                pw_field.send_keys(Keys.RETURN)
            print("  ✓ Password submitted")
        except Exception as e:
            print(f"  ⚠ Password field error ({e.__class__.__name__}) — fill manually")
    else:
        print("  ⚠ No password — complete login in the browser window")

    # ── Step 4: Wait for redirect back to Tableau ─────────────────────────────
    print(f"  Waiting up to {mfa_timeout}s for MFA / redirect…")
    try:
        WebDriverWait(driver, mfa_timeout).until(
            lambda d: tableau_host in d.current_url)
        print("  ✓ Back on Tableau Server")
        # Wait for at least one interactive element so the app is truly ready
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "nav, [data-tb-test-id='SiteNavigation'], .tab-nav-bar, main")))
    except Exception:
        print("  Timed out — continuing with current session")

    _handle_stay_signed_in(driver)


# ─── Extract Tableau REST token from the browser ─────────────────────────────

def _detect_api_version(base_url: str, session: requests.Session) -> str:
    """Query /api/2.3/serverinfo to get the latest supported REST API version."""
    try:
        r = session.get(f"{base_url}/api/2.3/serverinfo", timeout=10, verify=True)
        if r.ok:
            root   = ET.fromstring(r.text)
            ns     = {"t": "http://tableau.com/api"}
            el     = root.find(".//t:restApiVersion", ns)
            if el is not None and el.text:
                print(f"  Detected API version: {el.text.strip()}")
                return el.text.strip()
    except Exception:
        pass
    # Fall back to version from XSD hint in last error, or a safe default
    return "3.27"


def get_tableau_rest_token(driver: webdriver.Chrome,
                            base_url: str, site: str) -> tuple:
    """
    Exchange the live browser session for a Tableau REST API token.
    Copies browser cookies into a requests.Session and calls the REST
    signin endpoint from Python — no JS quoting issues.
    Returns (token, site_id, api_version).
    """

    # Copy all browser cookies into a requests session
    session = requests.Session()
    for c in driver.get_cookies():
        session.cookies.set(c["name"], c["value"],
                            domain=c.get("domain", ""))

    # Forward workgroup session as auth header
    wg = session.cookies.get("workgroup_session_id")
    if wg:
        session.headers["X-Tableau-Auth"] = wg

    # Auto-detect the correct API version for this server
    api_version = _detect_api_version(base_url, session)

    payload = (
        "<?xml version='1.0' encoding='UTF-8' ?>"
        "<tsRequest><credentials>"
        f"<site contentUrl=\"{site}\" />"
        "</credentials></tsRequest>"
    )
    signin_url = f"{base_url}/api/{api_version}/auth/signin"
    print(f"  POST {signin_url}")
    r = session.post(signin_url, data=payload,
                     headers={"Content-Type": "application/xml",
                               "Accept":       "application/xml"},
                     timeout=30, verify=True)

    print(f"  Response: {r.status_code}")
    if r.ok:
        try:
            root    = ET.fromstring(r.text)
            ns      = {"t": "http://tableau.com/api"}
            creds   = root.find(".//t:credentials", ns)
            site_el = root.find(".//t:site", ns)
            if creds is not None and site_el is not None:
                token   = creds.get("token", "")
                site_id = site_el.get("id", "")
                if token:
                    print(f"  ✓ REST token obtained — site_id={site_id}")
                    return token, site_id, api_version
        except Exception as e:
            print(f"  XML parse error: {e}")

    print(f"  REST signin response: {r.text[:400]}")
    raise RuntimeError(
        f"Could not obtain Tableau REST API token (HTTP {r.status_code})."
    )


# ─── Download workbook via REST API ──────────────────────────────────────────

def download_workbook_rest(base_url: str, site_id: str,
                            workbook_id: str, token: str,
                            output_dir: Path,
                            api_version: str = "3.27") -> Path:
    dl_url  = f"{base_url}/api/{api_version}/sites/{site_id}/workbooks/{workbook_id}/content"
    headers = {"X-Tableau-Auth": token}

    print(f"  GET {dl_url}")
    r = requests.get(dl_url, headers=headers, stream=True, timeout=120, verify=True)
    if not r.ok:
        raise RuntimeError(f"Download failed {r.status_code}: {r.text[:300]}")

    cd      = r.headers.get("Content-Disposition", "")
    fname_m = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\r\n]+)', cd, re.IGNORECASE)
    fname   = unquote(fname_m.group(1).strip()) if fname_m else f"workbook_{workbook_id}.twbx"
    if not fname.endswith(".twbx"):
        fname += ".twbx"

    out = output_dir / fname
    total = 0
    with open(out, "wb") as f:
        for chunk in r.iter_content(65536):
            if chunk:
                f.write(chunk)
                total += len(chunk)
                print(f"\r  {total/1_048_576:.1f} MB…", end="", flush=True)
    print()
    return out


# ─── UI download: ... menu → Download ────────────────────────────────────────

def ui_download_fallback(driver: webdriver.Chrome, base_url: str,
                          workbook_id: str, output_dir: Path,
                          timeout: int = 30, on_progress=None):
    """
    Replicates the manual flow visible in the screenshot:
      1. Navigate to the workbook details page
      2. Click the '...' (overflow / more-actions) button next to the title
      3. Click 'Download' in the dropdown
      4. Handle format-selection dialog if it appears
      5. Wait for the .twbx file to land in output_dir
    """
    # Build the workbook details URL
    current = driver.current_url
    site_m  = re.search(r"#/site/([^/]+)", current)
    site    = site_m.group(1) if site_m else "Default"
    target  = f"{base_url}/#/site/{site}/workbooks/{workbook_id}"

    print(f"  Navigating to: {target}")
    driver.get(target)

    # ── Wait for the workbook header + action buttons ────────────────────────
    print("  Waiting for workbook page…")
    try:
        WebDriverWait(driver, 20).until(EC.any_of(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "button[title='More actions'], "
                "button[aria-label='More actions'], "
                "[data-tb-test-id='workbook-overflow-button'], "
                "[data-tb-test-id='overflow-button']")),
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1")),
        ))
    except Exception:
        time.sleep(2)

    # Record start time BEFORE clicking anything — any .twbx with mtime ≥ this is new
    download_start = time.time()

    # ── Step 1: click '...' overflow — all candidates race in parallel ─────────
    print("  Clicking '...' overflow menu…")
    try:
        btn = WebDriverWait(driver, 10).until(EC.any_of(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "[data-tb-test-id='workbook-overflow-button']")),
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "[data-tb-test-id='workbook-actions-overflow-button']")),
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "[data-tb-test-id='overflow-button']")),
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "button[title='More actions']")),
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "button[aria-label='More actions']")),
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "button[aria-label='More options']")),
            EC.element_to_be_clickable((By.XPATH,
                "//button[normalize-space(text())='...' or normalize-space(text())='…']")),
        ))
        btn.click()
        print("  ✓ Overflow menu opened")
    except Exception:
        driver.save_screenshot(str(output_dir / "debug_overflow.png"))
        raise RuntimeError(
            f"Could not find '...' button — screenshot: {output_dir / 'debug_overflow.png'}")

    # ── Step 2: click 'Download' inside the open dropdown ─────────────────────
    # Wait for the menu to be visible before searching (condition-based, not fixed sleep)
    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "[role='menu'], ul[role='menu'], .tab-dropdown-content, .dropdown-menu")))
    except Exception:
        pass
    driver.save_screenshot(str(output_dir / "debug_dropdown_open.png"))
    print("  Screenshot: debug_dropdown_open.png")
    print("  Clicking 'Download'…")
    try:
        dl_el = None

        # Try all known data-tb-test-id values in one combined CSS selector — avoids
        # 5 × 1s sequential timeouts when none of the earlier IDs match.
        _test_ids = ("workbook-download-menuItem", "download-workbook-menuItem",
                     "workbook-download", "download-workbook", "download-button")
        _combined_sel = ", ".join(f"[data-tb-test-id='{tid}']" for tid in _test_ids)
        try:
            dl_el = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, _combined_sel)))
        except Exception:
            pass

        # Fallback: find 'Download' scoped to the open menu container so we
        # never accidentally click a hidden element elsewhere in the DOM.
        if dl_el is None:
            # Locate the visible open menu/dropdown container first
            menu_el = None
            for menu_sel in (
                "ul[role='menu']", "[role='menu']", "[role='listbox']",
                ".tab-dropdown-content", ".dropdown-menu",
            ):
                try:
                    candidate = driver.find_element(By.CSS_SELECTOR, menu_sel)
                    if candidate.is_displayed():
                        menu_el = candidate
                        break
                except Exception:
                    pass

            if menu_el:
                # Search only within the open menu — avoids matching hidden clones.
                # Use text() (direct text nodes only) to match the leaf element,
                # not a parent container that also contains other text.
                dl_el = menu_el.find_element(
                    By.XPATH,
                    ".//*[normalize-space(text())='Download']",
                )
            else:
                # Last resort: any visible element with exact text 'Download'
                dl_el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                    (By.XPATH,
                     "//*[normalize-space(text())='Download']"
                     "[not(ancestor::*[@aria-hidden='true'])]"
                    )))

        # Regular Selenium click — fires real browser events so React handlers fire
        dl_el.click()
        print("  ✓ 'Download' clicked")
    except Exception:
        driver.save_screenshot(str(output_dir / "debug_download_menu.png"))
        raise RuntimeError(
            f"Could not find 'Download' in dropdown — "
            f"screenshots: {output_dir / 'debug_dropdown_open.png'}, "
            f"{output_dir / 'debug_download_menu.png'}")

    # ── Step 3: format-selection dialog (Tableau Workbook .twbx) ──────────────
    # Wait for dialog to appear (condition-based) then screenshot
    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "[role='dialog'], .tab-modal, .tab-widget-overlay")))
    except Exception:
        pass
    driver.save_screenshot(str(output_dir / "debug_after_download_click.png"))
    print("  Screenshot: debug_after_download_click.png")
    try:
        opt = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH,
            "//*[normalize-space(text())='Tableau Workbook' or "
            " normalize-space(text())='Tableau Workbook (.twbx)' or "
            " normalize-space(text())='Packaged Workbook' or "
            " contains(normalize-space(text()),'.twbx')]")))
        opt.click()
        print("  ✓ Format selected")
        time.sleep(0.3)
        # Some dialogs need a confirm 'Download' button after selecting the format
        try:
            confirm = WebDriverWait(driver, 3).until(EC.element_to_be_clickable(
                (By.XPATH,
                 "//button[normalize-space(text())='Download'] | "
                 "//a[normalize-space(text())='Download']")))
            confirm.click()
            print("  ✓ Download confirmed")
        except Exception:
            pass
    except Exception:
        pass  # no format dialog → download already triggered directly

    # ── Step 4: wait for file ─────────────────────────────────────────────────
    print(f"  Waiting for .twbx in {output_dir} (also checking ~/Downloads)…")
    found = _wait_for_download(output_dir, timeout=600, start=download_start,
                               on_progress=on_progress)
    if not found:
        raise RuntimeError("Download finished but no .twbx / .twb file found in "
                           f"{output_dir} or ~/Downloads.")
    return found


def _wait_for_download(directory: Path, timeout: int = 90,
                       start: float = None, on_progress=None):
    """
    Poll every 0.5s until a Tableau workbook download completes.
    Returns the Path of the downloaded file, or None on timeout.

    Also checks ~/Downloads as a fallback because Chrome's CDP
    Page.setDownloadBehavior is sometimes ignored by certain sites,
    causing the file to land in the OS default instead of output_dir.
    """
    if start is None:
        start = time.time()
    deadline = start + timeout

    tableau_exts  = {".twbx", ".twb"}
    # Any file ≥ 50 KB that appeared after start is a candidate — catches
    # unexpected extensions (.zip, bare .twb, Content-Disposition quirks, etc.)
    FALLBACK_MIN_BYTES = 50_000

    # Check both the requested dir and the OS default Downloads folder
    alt_dir = Path.home() / "Downloads"
    dirs_to_check = [directory]
    if alt_dir.resolve() != directory.resolve() and alt_dir.is_dir():
        dirs_to_check.append(alt_dir)

    # Full snapshot of all files that existed before the download started
    skip_exts = {".crdownload", ".part", ".tmp"}
    snapshots = {}
    for d in dirs_to_check:
        snapshots[d] = {f: f.stat().st_mtime for f in d.iterdir() if f.is_file()}

    def _pick_file(d, snap, temp):
        """Return the best new/updated file in directory d, or None."""
        best = None
        for f in d.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() in skip_exts:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            old_mtime = snap.get(f)
            is_new     = old_mtime is None
            is_updated = (old_mtime is not None) and (st.st_mtime >= start - 2)
            if not (is_new or is_updated):
                continue
            if temp:        # don't report while a .crdownload sibling exists
                continue
            # Prefer tableau extensions; fall back to any large file
            if f.suffix.lower() in tableau_exts:
                return f
            if st.st_size >= FALLBACK_MIN_BYTES:
                best = f    # keep looking in case a .twbx also exists
        return best

    last_status_time = time.time()
    while time.time() < deadline:
        for d in dirs_to_check:
            temp = list(d.glob("*.crdownload")) + list(d.glob("*.part"))
            f = _pick_file(d, snapshots[d], temp)
            if f is not None:
                loc = f" (found in {d})" if d != directory else ""
                print(f"  ✓ Downloaded: {f.name}  ({f.stat().st_size/1_048_576:.1f} MB){loc}")
                return f

        # Progress indicator every 5s — show .crdownload size so we know it's moving
        if time.time() - last_status_time >= 5:
            for d in dirs_to_check:
                temp = list(d.glob("*.crdownload")) + list(d.glob("*.part"))
                if temp:
                    sizes = ", ".join(
                        f"{x.name} ({x.stat().st_size/1_048_576:.1f} MB)" for x in temp
                    )
                    print(f"  … downloading: {sizes}")
                    if on_progress:
                        mb = sum(x.stat().st_size for x in temp) / 1_048_576
                        on_progress(f"Downloading workbook… {mb:.1f} MB so far")
                else:
                    print(f"  … waiting in {d.name}")
            last_status_time = time.time()

        time.sleep(0.5)

    # Timed out — list everything in watched dirs to help diagnose where the file went
    print("  ⚠ Timed out. All files currently in watched folders:")
    for d in dirs_to_check:
        print(f"    [{d}]")
        for f in sorted(d.iterdir()):
            if f.is_file():
                age = time.time() - f.stat().st_mtime
                print(f"      {f.name}  ({f.stat().st_size} bytes, modified {age:.0f}s ago)")
    return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Download a Tableau workbook via SSO")
    ap.add_argument("url",          help="Any Tableau Server dashboard URL")
    ap.add_argument("--email", "-e", default="rajkumar.ganeshan@cbre.com",
                    help="Microsoft / SAML login email")
    ap.add_argument("--password", "-p", default="",
                    help="Password (omit to be prompted securely)")
    ap.add_argument("--output", "-o",  default=str(Path.home() / "Downloads"),
                    help="Output folder (default: ~/Downloads)")
    ap.add_argument("--mfa-timeout",   type=int, default=90,
                    help="Seconds to wait for MFA (default 90)")
    args = ap.parse_args()

    # Password: use --password flag, or leave blank to type it in the browser window
    password = args.password  # empty = user types it manually in the Chrome window

    output_dir = Path(args.output).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Parse URL
    print("\n[1/4] Parsing URL…")
    base_url, site, workbook_id = parse_tableau_url(args.url)
    print(f"  Server      : {base_url}")
    print(f"  Site        : {site}")
    print(f"  Workbook ID : {workbook_id}")

    # 2. Browser + SSO login
    print("\n[2/4] Logging in via Microsoft SSO…")
    driver = launch_browser(str(output_dir))
    try:
        selenium_login(driver, args.url,
                       email=args.email,
                       password=password,
                       mfa_timeout=args.mfa_timeout)

        # 3. Get REST token from the live browser session
        print("\n[3/4] Obtaining Tableau REST API token…")
        api_version = "3.27"
        try:
            token, site_id, api_version = get_tableau_rest_token(driver, base_url, site)
        except Exception as token_err:
            print(f"  REST token failed: {token_err}")
            token, site_id = None, None

        # 4. Download — try REST API first, then browser UI fallback
        print("\n[4/4] Downloading workbook…")
        if token and site_id:
            try:
                out = download_workbook_rest(base_url, site_id, workbook_id,
                                             token, output_dir, api_version)
                print(f"\n✓  Saved to: {out}")
            except Exception as e:
                print(f"  REST download failed: {e}")
                print("  Falling back to browser UI download…")
                ui_download_fallback(driver, base_url, workbook_id, output_dir)
        else:
            print("  No REST token — using browser UI download…")
            ui_download_fallback(driver, base_url, workbook_id, output_dir)
            print(f"\n✓  Saved via UI download to: {output_dir}")

    finally:
        driver.quit()
        print("  Browser closed.")


if __name__ == "__main__":
    main()
