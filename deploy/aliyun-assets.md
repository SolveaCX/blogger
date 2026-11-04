# Persistent cover images on the Aliyun API host

The API can store uploads on a persistent host volume. Use this when the
production service does not have a configured GCS bucket; otherwise
`/api/uploads` falls back to an inline `data:` URL, which cannot be used as a
public article cover URL.

Mount a persistent host directory at `/data/assets` in the API container, for
example `/srv/blogger-assets:/data/assets`, and set these server-side values:

```text
LOCAL_ASSET_DIR=/data/assets
PUBLIC_ASSET_BASE_URL=https://blog.solvea.io/api/assets
UPLOAD_PREFIX=uploads
```

The API process must be able to create files below `/data/assets`. Keep that
directory across container replacements and include it in host backups. The
asset endpoint is public by design; do not use it for private files. If both
`LOCAL_ASSET_DIR` and `GCS_BUCKET` are set, local storage takes precedence.

After the reviewed release is deployed, upload a small image with an authorized
account and verify that the returned URL starts with
`https://blog.solvea.io/api/assets/uploads/` and returns HTTP 200 with an image
Content-Type and nonempty body. Do not use the article publisher until this
readback succeeds.
