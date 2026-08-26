"""SUPERSEDED — do not run this. Kept only so the history reads straight.

`tools/build_manifest.py` now emits the `images` block itself (see
`_image_meta`), which is what this script used to bolt on afterwards. Running
it today does damage rather than work:

  - `root` is hardcoded to C:/fastapi/proofpay, so it cannot find this checkout.
  - It writes manifest.json with `open(..., "w")` and no `newline=`, so on
    Windows every one of the ~1,100 line endings becomes CRLF. That is exactly
    the failure `newline="\\n"` in build_manifest.py exists to prevent.
  - It hand-edits a GENERATED file, so the next `python tools/build_manifest.py`
    silently reverts whatever it did.

To refresh the hashes after re-rendering a receipt, run
`python tools/build_manifest.py`.
"""

import hashlib
import json
from pathlib import Path


def main():
    root = Path('C:/fastapi/proofpay')
    manifest_path = root / 'fixtures' / 'demo' / 'manifest.json'
    img_dir = root / 'fixtures' / 'demo' / 'images'
    
    with open(manifest_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    for case in data['cases']:
        img_id = case['id']
        file_path = img_dir / f"{img_id}.jpg"
        
        if not file_path.exists():
            print(f"Warning: Missing {file_path}")
            continue
            
        with open(file_path, 'rb') as imgF:
            file_bytes = imgF.read()
            # Calculate SHA256
            sha256 = hashlib.sha256(file_bytes).hexdigest()
            size = len(file_bytes)
            
        case['images'] = {
            'delivered': f"images/{img_id}.jpg",
            'sha256': sha256,
            'bytes': size
        }
        
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("Manifest populated with true SHA256 hashes for all images.")

if __name__ == '__main__':
    main()
