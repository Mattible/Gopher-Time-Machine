import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import shutil


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_timestamps(data: dict, target_date: str) -> dict:
    """Recursively zero out all known timestamp fields in an image config."""
    data['created'] = target_date
    for entry in data.get('history', []):
        if isinstance(entry, dict):
            entry['created'] = target_date
    cc = data.get('container_config') or data.get('config') or {}
    if isinstance(cc, dict) and 'Created' in cc:
        cc['Created'] = target_date
    return data


def backdate_oci(blobs_dir: str, index_path: str, extract_path: str, new_tag: str, target_date: str):
    """
    OCI image layout (Docker v25+): blobs are content-addressed under
    blobs/sha256/<digest>.  We must rehash every blob we touch and update
    all upstream references, otherwise Docker ignores our edits.
    """
    with open(index_path) as f:
        index = json.load(f)

    # ── locate manifest blob ──────────────────────────────────────────────────
    # index.json may point to a manifest list (OCI index) rather than an image
    # manifest directly — keep descending until we find a blob with 'config'.
    mfst_entry = index['manifests'][0]
    mfst_hash  = mfst_entry['digest'].split(':')[1]
    mfst_path  = os.path.join(blobs_dir, mfst_hash)

    with open(mfst_path) as f:
        mfst = json.load(f)

    # If this is a manifest list, drill into its first child manifest
    parent_entry = None
    parent_mfst  = None
    parent_hash  = None
    parent_path  = None
    if 'manifests' in mfst and 'config' not in mfst:
        parent_entry = mfst_entry
        parent_mfst  = mfst
        parent_hash  = mfst_hash
        parent_path  = mfst_path
        child_entry  = mfst['manifests'][0]
        child_hash   = child_entry['digest'].split(':')[1]
        child_path   = os.path.join(blobs_dir, child_hash)
        with open(child_path) as f:
            mfst = json.load(f)
        mfst_entry = child_entry
        mfst_hash  = child_hash
        mfst_path  = child_path

    # ── patch config blob ─────────────────────────────────────────────────────
    cfg_hash = mfst['config']['digest'].split(':')[1]
    cfg_path = os.path.join(blobs_dir, cfg_hash)

    print(f"[*] Patching config blob: {cfg_hash[:16]}...")
    with open(cfg_path) as f:
        cfg = json.load(f)

    cfg = patch_timestamps(cfg, target_date)

    new_cfg_bytes  = json.dumps(cfg).encode()          # compact — Docker is strict about size
    new_cfg_hash   = sha256_bytes(new_cfg_bytes)
    new_cfg_digest = f"sha256:{new_cfg_hash}"

    with open(os.path.join(blobs_dir, new_cfg_hash), 'wb') as f:
        f.write(new_cfg_bytes)
    if new_cfg_hash != cfg_hash:
        os.remove(cfg_path)

    # ── update manifest blob (new config digest + size) ───────────────────────
    mfst['config']['digest'] = new_cfg_digest
    mfst['config']['size']   = len(new_cfg_bytes)
    # embed the desired tag so `docker load` picks it up directly
    mfst.setdefault('annotations', {})['org.opencontainers.image.ref.name'] = new_tag

    new_mfst_bytes  = json.dumps(mfst).encode()
    new_mfst_hash   = sha256_bytes(new_mfst_bytes)
    new_mfst_digest = f"sha256:{new_mfst_hash}"

    with open(os.path.join(blobs_dir, new_mfst_hash), 'wb') as f:
        f.write(new_mfst_bytes)
    if new_mfst_hash != mfst_hash:
        os.remove(mfst_path)

    # ── update index.json (new manifest digest + size) ───────────────────────
    # mfst_entry is the child entry; update it in-place (it's a dict reference)
    mfst_entry['digest'] = new_mfst_digest
    mfst_entry['size']   = len(new_mfst_bytes)
    mfst_entry.setdefault('annotations', {})['org.opencontainers.image.ref.name'] = new_tag

    if parent_mfst is not None:
        # Rehash the parent manifest list blob (it now contains updated child digest)
        new_parent_bytes  = json.dumps(parent_mfst).encode()
        new_parent_hash   = sha256_bytes(new_parent_bytes)
        new_parent_digest = f"sha256:{new_parent_hash}"
        with open(os.path.join(blobs_dir, new_parent_hash), 'wb') as f:
            f.write(new_parent_bytes)
        if new_parent_hash != parent_hash:
            os.remove(parent_path)
        # Point index.json at the new parent blob
        parent_entry['digest'] = new_parent_digest
        parent_entry['size']   = len(new_parent_bytes)
        parent_entry.setdefault('annotations', {})['org.opencontainers.image.ref.name'] = new_tag

    with open(index_path, 'w') as f:
        json.dump(index, f)

    # Also patch legacy manifest.json (Docker reads RepoTags from here on load)
    legacy_manifest_path = os.path.join(extract_path, 'manifest.json')
    if os.path.exists(legacy_manifest_path):
        with open(legacy_manifest_path) as f:
            legacy = json.load(f)
        for entry in legacy:
            if entry.get('Config') and cfg_hash in entry['Config']:
                entry['Config'] = entry['Config'].replace(cfg_hash, new_cfg_hash)
            if entry.get('RepoTags'):
                entry['RepoTags'] = [new_tag]
        with open(legacy_manifest_path, 'w') as f:
            json.dump(legacy, f)


def backdate_legacy(extract_path: str, manifest_path: str, target_date: str):
    """Legacy Docker save format: flat config JSON, no content-addressing."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    cfg_name = manifest[0]['Config']
    cfg_path = os.path.join(extract_path, cfg_name)

    print(f"[*] Patching config: {cfg_name}")
    with open(cfg_path) as f:
        cfg = json.load(f)

    cfg = patch_timestamps(cfg, target_date)

    with open(cfg_path, 'w') as f:
        json.dump(cfg, f)

    # update RepoTags so the image loads with the right name
    for entry in manifest:
        if entry.get('RepoTags'):
            entry['RepoTags'] = [entry['RepoTags'][0]]   # keep source tag for tagging later

    with open(manifest_path, 'w') as f:
        json.dump(manifest, f)


def backdate_image(image_name: str, new_tag: str, target_date: str = "0001-01-01T00:00:00Z"):
    """
    Saves a Docker image, backdates every timestamp in its metadata to
    target_date, and loads it back under new_tag.
    """
    tmp_dir     = tempfile.mkdtemp()
    tar_path    = os.path.join(tmp_dir, "image.tar")
    mod_tar_path = os.path.join(tmp_dir, "image_mod.tar")

    try:
        # 1. Export
        print(f"[*] Exporting {image_name}...")
        subprocess.run(["docker", "save", image_name, "-o", tar_path], check=True)

        # 2. Extract
        extract_path = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_path)
        with tarfile.open(tar_path) as tar:
            tar.extractall(path=extract_path)

        # 3. Detect layout and patch
        index_path  = os.path.join(extract_path, "index.json")
        blobs_dir   = os.path.join(extract_path, "blobs", "sha256")
        mfst_path   = os.path.join(extract_path, "manifest.json")

        if os.path.exists(index_path) and os.path.isdir(blobs_dir):
            backdate_oci(blobs_dir, index_path, extract_path, new_tag, target_date)
        else:
            backdate_legacy(extract_path, mfst_path, target_date)

        # 4. Repackage
        print("[*] Repackaging image...")
        with tarfile.open(mod_tar_path, "w") as tar:
            for root, _dirs, files in os.walk(extract_path):
                for fname in files:
                    full = os.path.join(root, fname)
                    tar.add(full, arcname=os.path.relpath(full, extract_path))

        # 5. Load
        print(f"[*] Loading modified image...")
        result = subprocess.run(
            ["docker", "load", "-i", mod_tar_path],
            check=True, capture_output=True, text=True
        )
        print(result.stdout.strip())

        # 6. Tag using whatever ref docker load actually assigned
        loaded_ref = None
        for line in result.stdout.splitlines():
            if line.startswith('Loaded image ID:'):
                loaded_ref = line.split(':', 1)[1].strip()  # sha256:abc...
                break
            elif line.startswith('Loaded image:'):
                loaded_ref = line.split(':', 1)[1].strip()  # name:tag
                break

        if loaded_ref and loaded_ref != new_tag:
            print(f"[*] Tagging {loaded_ref} as {new_tag}")
            subprocess.run(["docker", "tag", loaded_ref, new_tag], check=True)
        elif not loaded_ref:
            raise RuntimeError(f"Could not parse loaded image ref from docker load output: {result.stdout!r}")

        print(f"\n[+] Done. Run: docker inspect --format='{{{{.Created}}}}' {new_tag}")

    finally:
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backdate a Docker image's creation timestamp."
    )
    parser.add_argument("source_image", help="Source image (e.g. oldest-whale:latest)")
    parser.add_argument("result_tag",   help="Tag for the backdated image (e.g. oldest-whale:year-one)")
    parser.add_argument(
        "target_date",
        nargs="?",
        default="0001-01-01T00:00:00Z",
        help="ISO 8601 timestamp to set (default: 0001-01-01T00:00:00Z)",
    )
    args = parser.parse_args()

    backdate_image(args.source_image, args.result_tag, args.target_date)
