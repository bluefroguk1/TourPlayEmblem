# Tourplay Team Icon Tool

A small self-hosted web tool: upload a photo or logo, it removes the
background using a local ML model (no image ever leaves your network unless
you expose it yourself), and exports a PNG that meets
[Tourplay.net's team emblem requirements](https://tourplay.net/en/support/content/(supportContent:manage-coaches/team-emblems)):

- PNG format with a fully transparent background
- At least 320 x 320 pixels (default output is 800 x 800, configurable up to
  1600 x 1600 in the UI)
- Under 2 MB
- Subject cropped to its visible pixels and centered so it fills most of the
  frame (Tourplay requires the emblem fill at least 3/4 of the display area)

Built to run on a Raspberry Pi in Docker, with Cloudflare Tunnel as the
suggested way to expose it to the internet later.

## Requirements

- Raspberry Pi 4 or 5 (4GB RAM or more recommended)
- **64-bit** Raspberry Pi OS (Bookworm or newer). This is important: the
  background-removal library depends on `onnxruntime`, which does not ship
  32-bit ARM wheels.
- Docker + the Docker Compose plugin installed on the Pi
  ([official install instructions](https://docs.docker.com/engine/install/debian/))

## Quick start (on the Pi)

```bash
git clone <your-repo-url> tourplay-icon-tool
cd tourplay-icon-tool
docker compose build
docker compose up -d
```

First build will take a few minutes (installing Python deps). The **first
time you process an image**, the app downloads the background-removal model
(~176 MB, one-time) — this is cached in a Docker volume so it survives
restarts and rebuilds.

Once it's up, open `http://<pi-ip-address>:8600` from any device on your
network.

`8600` was picked because on this Pi, `8000` is Portainer and `8080` was also
taken. If it's ever taken on yours too, no need to edit any files — just
create a `.env` next to `docker-compose.yml`:

```
HOST_PORT=<some other free port>
```

then `docker compose up -d` again. The container always listens on 8000
internally; `HOST_PORT` only changes which port it's reachable on from
outside the container.

To see everything already listening on the Pi (handy for picking a free
port): `sudo ss -tulpn | grep LISTEN`. Also worth a `docker ps -a` check for
a stale container still holding a port from an earlier attempt — remove one
with `docker rm -f <name>` if you find it.

### Updating after a code change

```bash
git pull
docker compose build
docker compose up -d
```

## How it works

1. You upload an image (PNG/JPEG/WEBP/BMP/GIF).
2. A local ML model ([rembg](https://github.com/danielgatis/rembg), U²-Net)
   removes the background, producing a transparent PNG.
3. The result is cropped to its visible content. The output canvas size is
   then chosen automatically for that specific image: close to its native
   resolution (so nothing is upscaled beyond what the source actually
   contains), clamped between 320x320 (Tourplay's minimum) and 1600x1600
   (a sensible cap for an icon-sized image). The subject is centered on
   that square, transparent canvas, scaled to fill ~85% of the frame.
4. If the encoded PNG would still exceed Tourplay's 2 MB limit, the tool
   automatically shrinks the canvas further (never below 320x320) until it
   fits.
5. You get a preview and a download button — no size to choose, every
   export already satisfies Tourplay's rules.

Everything runs locally on the Pi — no external API calls, no image
uploads to a third party.

### When automatic background removal can't find a subject

Occasionally the model can't confidently separate a subject from the
background at all (a texture-heavy photo, a low-contrast image, anything
without a clear foreground object). Rather than exporting a broken result,
the tool detects this case and shows a manual crop tool instead: drag a box
over the part of your original image you want to keep, confirm, and that
selection is run back through the same pipeline. This only appears as a
fallback — most uploads never see it.

### Performance expectations

On a Pi 4/5, background removal typically takes a few seconds per image
once the model is loaded (the app loads it once at startup, not per
request). The very first request after a fresh container start may take a
little longer while the model warms up.

## Exposing it to the internet with Cloudflare Tunnel (when you're ready)

You don't need to open any ports on your router.

1. In the [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com/),
   go to **Networks &rarr; Tunnels &rarr; Create a tunnel**, choose
   "Cloudflared", and give it a name.
2. Add a **public hostname** (e.g. `icons.yourdomain.com`) pointing at
   service `http://tourplay-icon-tool:8000` (the container name/port from
   `docker-compose.yml` — Docker Compose puts both containers on the same
   network so this resolves by name).
3. Copy the tunnel token Cloudflare gives you.
4. In this project, create a `.env` file next to `docker-compose.yml`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=<paste your token here>
   ```
5. Uncomment the `cloudflared` service block in `docker-compose.yml`.
6. Start it:
   ```bash
   docker compose --profile tunnel up -d
   ```

Your tool is now reachable at the hostname you configured, with Cloudflare
handling TLS. Keep `.env` out of git (it's already in `.gitignore`).

## Configuration

Output size is fully automatic — there's nothing to pick in the UI. To
change the bounds it's chosen within, edit `MIN_DIMENSION` (Tourplay's
required minimum, don't lower this) and `MAX_CANVAS_SIZE` (the upscale cap)
near the top of `backend/processing.py`.

## Project layout

```
backend/
  app.py          FastAPI app: HTTP routes, upload handling
  processing.py   Background removal + crop/resize/compress pipeline
  requirements.txt
frontend/
  index.html      Single-page UI
  style.css
  app.js
Dockerfile
docker-compose.yml
```

## Troubleshooting

- **Container gets killed / runs out of memory**: the U²-Net model needs
  roughly 1-1.5 GB of RAM during inference. On a 2GB Pi this can be tight if
  other things are running; a Pi 4/5 with 4GB+ is recommended.
- **First image takes a very long time**: check `docker compose logs -f` —
  if it's still downloading the model, this is a one-time ~176MB fetch.
- **Slow on every request, not just the first**: make sure you didn't
  remove `--workers 1` from the Dockerfile's `CMD` and start multiple
  workers — each one loads its own copy of the model into memory and
  competes for CPU on the Pi.
