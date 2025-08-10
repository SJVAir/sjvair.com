import contextlib

from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm


def stream_to_disk(url: str, dest: Path, verify: bool = True) -> Path:
    """
    Stream a potentially large file to disk with retries and atomic rename.

    - Uses a temporary .part file in the same directory then renames atomically.
    - Prints coarse progress updates roughly every 50 MB when Content-Length is known.
    """
    # Retry policy
    retries = requests.adapters.Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504, 429, 404, 400, 202],
        allowed_methods={"GET"},  # set, uppercased per urllib3
        raise_on_status=False,
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SJVAir Downloader)",
        "Accept": "*/*",
    }

    # Ensure destination directory exists
    dest.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.mount("http://", requests.adapters.HTTPAdapter(max_retries=retries))
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=retries))

    print("\nDownloading file:")
    print(f"-> URL:  {url}")
    print(f"-> Dest: {dest}\n")

    response = session.get(url, headers=headers, verify=verify, stream=True, timeout=(15, 600))
    response.raise_for_status()

    tmp = dest.with_suffix(dest.suffix + ".part")
    total = int(response.headers.get('content-length', 0))

    chunk_size = 1024 * 1024  # 1 MB

    try:
        with open(tmp, 'wb') as f, tqdm(total=total, unit='B', unit_scale=True, desc='Downloading') as bar:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))

        # Atomic replace
        tmp.replace(dest)
        return dest

    except Exception:
        # Best effort: if something went wrong, remove the partial file
        with contextlib.suppress(Exception):
            if tmp.exists():
                tmp.unlink()
        raise

