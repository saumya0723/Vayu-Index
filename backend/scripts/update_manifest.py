import json
import hashlib
from pathlib import Path
import sys

def main():
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / 'config' / 'phase14_publication_manifest.json'
    
    with manifest_path.open('r', encoding='utf-8') as f:
        manifest = json.load(f)
        
    updated = 0
    for pub in manifest.get('publications', []):
        file_path = root / pub['path']
        if file_path.exists():
            content = file_path.read_bytes()
            # Always normalize to LF line endings for cross-platform stability
            lf_content = content.replace(b'\r\n', b'\n')
            new_hash = hashlib.sha256(lf_content).hexdigest()
            if pub['sha256'] != new_hash:
                pub['sha256'] = new_hash
                updated += 1
                
    if updated > 0:
        with manifest_path.open('w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
            f.write('\n')
        print(f"Manifest updated successfully. {updated} publication hashes recalculated.")
    else:
        print("Manifest is already up-to-date. No hashes changed.")

if __name__ == '__main__':
    main()
